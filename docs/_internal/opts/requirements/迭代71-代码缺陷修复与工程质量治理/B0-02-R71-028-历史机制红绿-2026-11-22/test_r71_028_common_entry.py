"""R71-028: measure target full-column equality scans using a shared API."""

from datetime import datetime
from pathlib import Path
from threading import Lock

import numpy as np
import pandas as pd
import pytest

from backtrader.bokeh.live import datahandler
from backtrader.bokeh.live.datahandler import LiveDataHandler


@pytest.mark.parametrize("n_updates", [3, 7, 11])
def test_existing_updates_avoid_per_row_index_equality_scans(monkeypatch, n_updates):
    assert (
        Path(datahandler.__file__).resolve()
        == (Path.cwd() / "backtrader/bokeh/live/datahandler.py").resolve()
    )
    count = 96
    stamp = datetime(2024, 1, 1)
    initial = pd.DataFrame(
        {
            "index": range(count),
            "datetime": [stamp] * count,
            "close": [float(i) for i in range(count)],
            "volume": [100.0] * count,
        },
        index=pd.Index(range(count)),
    )
    ids = list(range(20, 20 + n_updates))
    rows = pd.DataFrame(
        {
            "index": ids,
            "datetime": [stamp] * n_updates,
            "close": [1000.0 + i for i in ids],
            "volume": [200.0] * n_updates,
        },
        index=pd.Index(ids),
    )
    handler = LiveDataHandler.__new__(LiveDataHandler)
    handler._datastore = initial.copy()
    handler._lookback = count
    handler._lock = Lock()
    handler._patches = []
    events = []
    handler._push_patches = lambda: events.append("patch")
    handler._push_adds = lambda: events.append("add")

    scans = []
    original_eq = pd.Series.__eq__

    def observed_eq(series, other):
        if series.name == "index" and isinstance(other, (int, np.integer)):
            scans.append((len(series), int(other)))
        return original_eq(series, other)

    with monkeypatch.context() as guard:
        guard.setattr(pd.Series, "__eq__", observed_eq)
        handler._process(rows)

    expected = initial.copy()
    for idx in ids:
        expected.loc[idx] = rows.loc[idx]
    pd.testing.assert_frame_equal(handler._datastore, expected)
    assert events == ["patch"] * n_updates
    assert len(handler._patches) == n_updates
    assert scans == [], f"per-row full-index equality scans: {scans!r}"

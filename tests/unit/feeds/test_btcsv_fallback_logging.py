"""Regression coverage for the Backtrader CSV feed's line-write fallback."""

from types import SimpleNamespace

import backtrader.feeds.btcsv as btcsv


class _RejectingArray:
    def __setitem__(self, index, value):
        raise IndexError("buffer boundary")


class _Line:
    def __init__(self):
        self._idx = 0
        self._default_value = 0.0
        self.array = _RejectingArray()
        self.bindings = []
        self.value = None

    def __setitem__(self, index, value):
        assert index == 0
        self.value = value


def test_btcsv_direct_write_indexerror_logs_fallback_and_preserves_values(monkeypatch):
    lines = [_Line() for _ in range(7)]
    data = SimpleNamespace(_btcsv_line_refs=tuple(lines))
    messages = []
    monkeypatch.setattr(btcsv, "logger", SimpleNamespace(debug=messages.append))

    result = btcsv.BacktraderCSVData._loadline(
        data,
        ["2026-11-21", "09:30:00", "1", "2", "0.5", "1.5", "10", "0"],
    )

    assert result is True
    assert lines[0].value > 0
    assert [line.value for line in lines[1:]] == [1.0, 2.0, 0.5, 1.5, 10.0, 0.0]
    assert len(messages) == 1
    assert "LineBuffer fallback" in messages[0]
    assert "ignored" not in messages[0]
    assert "btcsv:181" not in messages[0]

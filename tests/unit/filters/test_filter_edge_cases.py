#!/usr/bin/env python
"""Regression tests for filter edge-case fixes.

Covers:
- P0: CalendarDays._fillbars — None > 0 TypeError with default fill_price
- P1: Renko.nextstart — division by zero when autosize=0
"""

import pytest


# ---------------------------------------------------------------------------
# P0: CalendarDays._fillbars — fill_price=None causes TypeError
# ---------------------------------------------------------------------------

class TestCalendarDaysFillPrice:
    """Verify CalendarDays handles fill_price=None without TypeError."""

    def test_fill_price_none_no_typeerror(self):
        """Default fill_price=None must not crash with None > 0."""
        from backtrader.filters.calendardays import CalendarDays
        from types import SimpleNamespace
        from datetime import date, datetime, timedelta

        # Create a minimal data stub
        data = SimpleNamespace()
        data.close = {-1: 100.0}
        data.high = {-1: 105.0}
        data.low = {-1: 95.0}
        data.DateTime = 0
        data.Open = 1
        data.High = 2
        data.Low = 3
        data.Close = 4
        data.Volume = 5
        data.OpenInterest = 6

        # Stub methods
        data.size = lambda: 7
        data.date2num = lambda dt: 0.0
        data.lines = {i: {0: 0.0} for i in range(7)}
        added_bars = []
        data._add2stack = lambda bar: added_bars.append(bar)
        data._save2stack = lambda erase=False: None

        # Stub datetime
        dt_ns = SimpleNamespace()
        dt_ns.time = lambda idx=0: datetime.min.time()
        dt_ns.date = lambda: date(2024, 1, 3)
        data.datetime = dt_ns

        # Create CalendarDays filter with default fill_price=None
        filt = CalendarDays(data)

        # Simulate _fillbars with a 2-day gap
        dt_current = date(2024, 1, 3)
        dt_last = date(2024, 1, 1)

        # Before fix: TypeError: '>' not supported between NoneType and int
        filt._fillbars(data, dt_current, dt_last)

        # Fills 2 bars (Jan 2 and Jan 3 — loop increments before filling)
        assert len(added_bars) == 2

    def test_fill_price_positive(self):
        """fill_price > 0 should use the given price."""
        from backtrader.filters.calendardays import CalendarDays
        from types import SimpleNamespace
        from datetime import date, datetime

        data = SimpleNamespace()
        data.DateTime = 0
        data.Open = 1
        data.High = 2
        data.Low = 3
        data.Close = 4
        data.Volume = 5
        data.OpenInterest = 6
        data.size = lambda: 7
        data.date2num = lambda dt: 0.0
        data.lines = {i: {0: 0.0} for i in range(7)}
        added_bars = []
        data._add2stack = lambda bar: added_bars.append(bar)
        data._save2stack = lambda erase=False: None

        dt_ns = SimpleNamespace()
        dt_ns.time = lambda idx=0: datetime.min.time()
        data.datetime = dt_ns

        filt = CalendarDays(data, fill_price=42.0)

        dt_current = date(2024, 1, 3)
        dt_last = date(2024, 1, 1)
        filt._fillbars(data, dt_current, dt_last)

        assert len(added_bars) == 2  # no crash, correct bar count

    def test_fill_price_midpoint(self):
        """fill_price=-1 should use high-low midpoint."""
        from backtrader.filters.calendardays import CalendarDays
        from types import SimpleNamespace
        from datetime import date, datetime

        data = SimpleNamespace()
        data.high = {-1: 110.0}
        data.low = {-1: 90.0}
        data.DateTime = 0
        data.Open = 1
        data.High = 2
        data.Low = 3
        data.Close = 4
        data.Volume = 5
        data.OpenInterest = 6
        data.size = lambda: 7
        data.date2num = lambda dt: 0.0
        data.lines = {i: {0: 0.0} for i in range(7)}
        added_bars = []
        data._add2stack = lambda bar: added_bars.append(bar)
        data._save2stack = lambda erase=False: None

        dt_ns = SimpleNamespace()
        dt_ns.time = lambda idx=0: datetime.min.time()
        data.datetime = dt_ns

        filt = CalendarDays(data, fill_price=-1)

        dt_current = date(2024, 1, 3)
        dt_last = date(2024, 1, 1)
        filt._fillbars(data, dt_current, dt_last)

        assert len(added_bars) == 2  # no crash, correct bar count


# ---------------------------------------------------------------------------
# P1: Renko.nextstart — autosize=0 division by zero
# ---------------------------------------------------------------------------

class TestRenkoAutosizeGuard:
    """Verify Renko handles autosize=0 without ZeroDivisionError."""

    def test_autosize_zero_no_crash(self):
        """autosize=0 should not crash; falls back to size=1.0."""
        from backtrader.filters.renko import Renko
        from types import SimpleNamespace

        data = SimpleNamespace()
        data.open = {0: 100.0}

        # Create Renko with autosize=0, size=None
        filt = Renko(data, autosize=0.0)

        # Before fix: ZeroDivisionError in o // self.p.autosize
        filt.nextstart(data)

        assert filt._size == 1.0  # fallback value

    def test_autosize_normal(self):
        """Normal autosize should compute size correctly."""
        from backtrader.filters.renko import Renko
        from types import SimpleNamespace

        data = SimpleNamespace()
        data.open = {0: 100.0}

        filt = Renko(data, autosize=20.0)
        filt.nextstart(data)

        # 100.0 // 20.0 = 5.0
        assert filt._size == 5.0

    def test_explicit_size_ignores_autosize(self):
        """When size is explicitly set, autosize is not used."""
        from backtrader.filters.renko import Renko
        from types import SimpleNamespace

        data = SimpleNamespace()
        data.open = {0: 100.0}

        filt = Renko(data, size=10.0, autosize=0.0)
        filt.nextstart(data)

        assert filt._size == 10.0

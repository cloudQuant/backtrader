"""Cross-version FIR and signal precision under Cerebro execution modes."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


def _values():
    return [
        (-1.0 if i % 2 else 1.0) * 1.0e16 + (i % 19) * 2.0
        for i in range(220)
    ]


class _Segmented(bt.indicators.DigitalMacd):
    def once(self, start, end):
        while start < end:
            stop = min(start + (7 if start % 2 else 31), end)
            super().once(start, stop)
            start = stop


def _reference(values, indicator_type, signal_period, point=0.01):
    fast = indicator_type.FAST_COEFFS
    slow = indicator_type.SLOW_COEFFS
    lookback = max(len(fast), len(slow))
    macds = []
    signals = []
    for index in range(len(values)):
        if index + 1 < lookback:
            macd = float("nan")
        else:
            a = b = 0.0
            for tap, coeff in enumerate(fast):
                a += coeff * values[index - tap]
            for tap, coeff in enumerate(slow):
                b += coeff * values[index - tap]
            macd = (a - b) / point
            if not math.isfinite(macd):
                macd = float("nan")
        macds.append(macd)
        window = macds[-signal_period:]
        if len(window) == signal_period and all(math.isfinite(v) for v in window):
            value = sum(window) / signal_period
            signals.append(value if math.isfinite(value) else float("nan"))
        else:
            signals.append(float("nan"))
    return macds, signals


@pytest.mark.parametrize("runonce,segmented,python_path", [
    (False, False, False),
    (True, False, False),
    (True, True, False),
    (True, True, True),
])
def test_digital_macd_uses_original_float_operations(
    monkeypatch, runonce, segmented, python_path
):
    import backtrader.indicators.contrib.digital_macd as module

    if python_path:
        monkeypatch.setattr(module, "_np", None)
    indicator_type = _Segmented if segmented else bt.indicators.DigitalMacd

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = indicator_type(self.data, signal_period=5)

    values = _values()
    frame = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values)},
        index=[datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(len(values))],
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    expected = _reference(values, indicator_type, 5)
    for actual, reference in zip(
        (strategy.indicator.macd.array, strategy.indicator.signal.array), expected
    ):
        assert len(actual) == len(reference)
        for got, want in zip(actual, reference):
            if math.isnan(want):
                assert math.isnan(got)
            else:
                assert got.hex() == want.hex()


@pytest.mark.parametrize("runonce", [False, True])
def test_digital_macd_strict_context_rejects_generated_infinity(runonce):
    class StrictContext:
        phase = None

        def asset_for(self, operation):
            return None

        def wrap(self, error, phase, asset):
            return RuntimeError("strict generated infinity")

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(
                self.data, signal_period=5, point=1.0e-308
            )
            self.indicator._factor_strict_context = StrictContext()

    values = [100.0 + i for i in range(100)]
    frame = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values)},
        index=[datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(len(values))],
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    with pytest.raises(RuntimeError, match="strict generated infinity"):
        cerebro.run(runonce=runonce, preload=True)


@pytest.mark.parametrize("runonce", [False, True])
def test_digital_macd_signal_only_strict_context_rejects_infinity(runonce):
    class StrictContext:
        phase = None

        def asset_for(self, operation):
            return None

        def wrap(self, error, phase, asset):
            return RuntimeError("signal strict infinity")

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(
                self.data, signal_period=5, point=0.01
            )
            self.indicator.l.signal._factor_strict_context = StrictContext()

    values = [1.0e307 * (1.0 + 0.4 * math.sin(i * 0.03)) for i in range(160)]
    frame = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values)},
        index=[datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(len(values))],
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    with pytest.raises(RuntimeError, match="signal strict infinity"):
        cerebro.run(runonce=runonce, preload=True)


@pytest.mark.parametrize("runonce", [False, True])
def test_digital_macd_samples_only_its_async_source_clock(runonce):
    def frame(count, step, offset):
        values = [100.0 + 0.13 * i + math.sin(i / 7.0) for i in range(count)]
        return values, pd.DataFrame(
            {"open": values, "high": values, "low": values, "close": values,
             "volume": [1.0] * count},
            index=[datetime(2024, 1, 1) + timedelta(minutes=step * i + offset)
                   for i in range(count)],
        )

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(
                self.datas[1], point=0.2, signal_period=7
            )

    _, fast = frame(400, 1, 0)
    values, slow = frame(180, 2, 1)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=fast))
    cerebro.adddata(bt.feeds.PandasData(dataname=slow))
    cerebro.addstrategy(Probe)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    expected = _reference(values, bt.indicators.DigitalMacd, 7, point=0.2)
    for actual, reference in zip(
        (strategy.indicator.macd.array, strategy.indicator.signal.array), expected
    ):
        assert len(actual) == len(reference)
        for got, want in zip(actual, reference):
            if math.isnan(want):
                assert math.isnan(got)
            else:
                assert got.hex() == want.hex()


@pytest.mark.parametrize("signal_period", [5, 128])
def test_digital_macd_replay_revises_current_bar_instead_of_adding_history(signal_period):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(
                self.data, signal_period=signal_period
            )
            self.values = []
            self.revisions = 0
            self.finite = 0

        def prenext(self):
            self._check_revision()

        def nextstart(self):
            self._check_revision()

        def next(self):
            self._check_revision()

        def _check_revision(self):
            length = len(self.data)
            if not length:
                return
            value = float(self.data.close[0])
            if length == len(self.values):
                self.values[-1] = value
                self.revisions += 1
            else:
                assert length == len(self.values) + 1
                self.values.append(value)
            expected = _reference(
                self.values, bt.indicators.DigitalMacd, signal_period
            )
            if signal_period >= 128:
                assert self.indicator._signal_nonfinite_count == sum(
                    not math.isfinite(value)
                    for value in self.indicator._signal_history
                )
            for line, reference in zip(
                (self.indicator.macd, self.indicator.signal), expected
            ):
                got, want = float(line[0]), reference[-1]
                if math.isnan(want):
                    assert math.isnan(got)
                else:
                    assert got.hex() == want.hex()
                    self.finite += 1

    values = [100.0 + i * 0.13 + math.sin(i / 7.0) for i in range(1000)]
    frame = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values)},
        index=[datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(len(values))],
    )
    source = bt.feeds.PandasData(
        dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=1
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.replaydata(source, timeframe=bt.TimeFrame.Minutes, compression=5)
    cerebro.addstrategy(Probe)
    strategy = cerebro.run()[0]
    assert strategy.revisions > 0
    assert strategy.finite > 0


@pytest.mark.parametrize("failure,signal_period", [
    ("close_read", 5),
    ("close_read", 128),
    ("macd_write", 5),
    ("macd_write", 128),
    ("signal_write", 5),
])
def test_digital_macd_replay_failed_revision_can_retry_without_state_loss(
    failure, signal_period
):
    class StrictContext:
        phase = None

        def asset_for(self, operation):
            return None

        def wrap(self, error, phase, asset):
            return RuntimeError("injected strict infinity")

    def number(value):
        value = float(value)
        return "nan" if math.isnan(value) else value.hex()

    def run(inject):
        class RevisionProbe(bt.indicators.DigitalMacd):
            def __init__(self):
                super().__init__()
                self.failure_observed = False

            def snapshot(self):
                return (
                    tuple(number(value) for value in self._closes),
                    tuple(number(value) for value in self._signal_history),
                    self._signal_nonfinite_count,
                    self._last_source_length,
                    number(self.macd[0]),
                    number(self.signal[0]),
                )

            def _signal_will_overflow(self):
                closes = (tuple(self._closes)[:-1] + (float(self.data.close[0]),))
                if len(closes) < self._max_lookback:
                    return False
                fast = slow = 0.0
                for index, coefficient in enumerate(self._fast_coeffs):
                    fast += coefficient * closes[-index - 1]
                for index, coefficient in enumerate(self._slow_coeffs):
                    slow += coefficient * closes[-index - 1]
                macd = (fast - slow) / self._point
                history = tuple(self._signal_history)[:-1] + (macd,)
                return (
                    len(history) == self._signal_period
                    and all(math.isfinite(value) for value in history)
                    and math.isinf(sum(history))
                )

            def next(self):
                ready = (
                    inject and not self.failure_observed and len(self.data) > 70
                    and self._last_source_length == len(self.data)
                )
                if ready and failure == "signal_write":
                    ready = self._signal_will_overflow()
                if not ready:
                    return super().next()

                before = self.snapshot()
                line = {
                    "close_read": self.data.close,
                    "macd_write": self.l.macd,
                    "signal_write": self.l.signal,
                }[failure]
                original = line.array[line.idx]
                if failure == "close_read":
                    line.array[line.idx] = float("inf")
                line._factor_strict_context = StrictContext()
                try:
                    with pytest.raises(RuntimeError, match="injected strict infinity"):
                        super().next()
                finally:
                    del line._factor_strict_context
                    if failure == "close_read":
                        line.array[line.idx] = original
                assert self.snapshot() == before
                super().next()
                self.failure_observed = True

        class Probe(bt.Strategy):
            def __init__(self):
                self.point = 1.0e-310 if failure == "macd_write" else 0.01
                self.indicator = RevisionProbe(
                    self.data, point=self.point, signal_period=signal_period
                )
                self.observations = []
                self.source_values = []

            def prenext(self):
                self._capture()

            def nextstart(self):
                self._capture()

            def next(self):
                self._capture()

            def _capture(self):
                if len(self.data):
                    length = len(self.data)
                    close = float(self.data.close[0])
                    if length == len(self.source_values):
                        self.source_values[-1] = close
                    else:
                        assert length == len(self.source_values) + 1
                        self.source_values.append(close)
                    expected = _reference(
                        self.source_values, bt.indicators.DigitalMacd,
                        signal_period, self.point
                    )
                    assert number(self.indicator.macd[0]) == number(expected[0][-1])
                    assert number(self.indicator.signal[0]) == number(expected[1][-1])
                    self.observations.append(
                        (length, number(self.indicator.macd[0]),
                         number(self.indicator.signal[0]))
                    )

        if failure == "signal_write":
            values = [1.0e307 * (1.0 + 0.4 * math.sin(i * 0.03)) for i in range(1000)]
        else:
            values = [100.0 + i * 0.13 + math.sin(i / 7.0) for i in range(1000)]
        frame = pd.DataFrame(
            {"open": values, "high": values, "low": values, "close": values,
             "volume": [1.0] * len(values)},
            index=[datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(len(values))],
        )
        source = bt.feeds.PandasData(
            dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=1
        )
        cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
        cerebro.replaydata(source, timeframe=bt.TimeFrame.Minutes, compression=5)
        cerebro.addstrategy(Probe)
        return cerebro.run()[0]

    control = run(False)
    recovered = run(True)
    assert recovered.indicator.failure_observed
    assert recovered.observations == control.observations


@pytest.mark.parametrize("storage", ["ordinary", "extended", "qbuffer"])
@pytest.mark.parametrize("failing_output", ["macd", "signal"])
def test_digital_macd_replay_failed_binding_restores_plain_linebuffers(
    storage, failing_output
):
    from backtrader.linebuffer import LineBuffer

    class FailingBinding:
        _is_datetime_line = False

        def __setitem__(self, ago, value):
            raise RuntimeError("injected signal binding failure")

    class RevisionProbe(bt.indicators.DigitalMacd):
        def __init__(self):
            super().__init__()
            self.binding_failure_observed = False

        def next(self):
            if (
                self.binding_failure_observed or len(self.data) <= 70
                or self._last_source_length != len(self.data)
            ):
                return super().next()

            target = LineBuffer()
            if storage == "qbuffer":
                target.qbuffer()
            target.forward()
            target[0] = 999.0
            if storage == "extended":
                target.idx = 3
            nested = LineBuffer()
            nested.forward()
            nested[0] = 333.0
            signal_target = LineBuffer()
            signal_target.forward()
            signal_target[0] = 777.0
            target.bindings.append(nested)
            self.l.macd.bindings.append(target)
            self.l.signal.bindings.append(signal_target)
            bad = FailingBinding()
            failing_line = self.l.macd if failing_output == "macd" else self.l.signal
            failing_line.bindings.append(bad)

            def snapshot():
                return (
                    tuple(self._closes), tuple(self._signal_history),
                    self._signal_nonfinite_count, self._last_source_length,
                    self.macd[0], self.signal[0], tuple(target.array),
                    tuple(nested.array), tuple(signal_target.array),
                )

            before = snapshot()
            try:
                with pytest.raises(RuntimeError, match="injected signal binding failure"):
                    super().next()
                assert snapshot() == before
                failing_line.bindings.remove(bad)
                super().next()
                assert target.array[target.idx] == self.macd[0]
                assert nested[0] == self.macd[0]
                assert signal_target[0] == self.signal[0]
                self.binding_failure_observed = True
            finally:
                self.l.macd.bindings.remove(target)
                self.l.signal.bindings.remove(signal_target)
                if bad in failing_line.bindings:
                    failing_line.bindings.remove(bad)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = RevisionProbe(self.data, signal_period=5)
            self.source_values = []

        def prenext(self):
            self._check()

        def nextstart(self):
            self._check()

        def next(self):
            self._check()

        def _check(self):
            length = len(self.data)
            if not length:
                return
            close = float(self.data.close[0])
            if length == len(self.source_values):
                self.source_values[-1] = close
            else:
                assert length == len(self.source_values) + 1
                self.source_values.append(close)
            expected = _reference(self.source_values, bt.indicators.DigitalMacd, 5)
            for line, reference in zip(
                (self.indicator.macd, self.indicator.signal), expected
            ):
                got, want = float(line[0]), reference[-1]
                if math.isnan(want):
                    assert math.isnan(got)
                else:
                    assert got.hex() == want.hex()

    values = [100.0 + i * 0.13 + math.sin(i / 7.0) for i in range(450)]
    frame = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values)},
        index=[datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(len(values))],
    )
    source = bt.feeds.PandasData(
        dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=1
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.replaydata(source, timeframe=bt.TimeFrame.Minutes, compression=5)
    cerebro.addstrategy(Probe)
    strategy = cerebro.run()[0]
    assert strategy.indicator.binding_failure_observed


def test_digital_macd_long_signal_recovers_after_nonfinite_source():
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.DigitalMacd(self.data, signal_period=5000)

    values = [100.0 + i * 0.01 + math.sin(i / 11.0) for i in range(5400)]
    values[100] = float("nan")
    frame = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values)},
        index=[datetime(2024, 1, 1) + timedelta(minutes=i) for i in range(len(values))],
    )
    outputs = []
    for runonce in (False, True):
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(Probe)
        strategy = cerebro.run(runonce=runonce, preload=True)[0]
        outputs.append((list(strategy.indicator.macd.array), list(strategy.indicator.signal.array)))

    for stepped, batch in zip(*outputs):
        assert len(stepped) == len(batch)
        for got, want in zip(stepped, batch):
            if math.isnan(want):
                assert math.isnan(got)
            else:
                assert got.hex() == want.hex()
    assert math.isnan(outputs[0][1][5000])
    assert math.isfinite(outputs[0][1][-1])

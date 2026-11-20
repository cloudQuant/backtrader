"""Regression coverage for PPO signal-line seeding in runonce mode (R71-154)."""

import math
from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind


def _prices(length):
    """Build a deterministic, non-linear close series for PPO calculations."""
    return [
        100.0 + index * 0.65 + ((index * 7) % 11 - 5) * 0.8
        for index in range(length)
    ]


def _run_ppo(
    indicator_cls,
    prices,
    period1,
    period2,
    period_signal,
    runonce,
    input_sma_period=None,
):
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2024-01-01", periods=len(prices), freq="D"),
    )
    result = {}

    class PPOProbeStrategy(bt.Strategy):
        def __init__(self):
            ppo_input = self.data.close
            if input_sma_period is not None:
                self.input_sma = btind.SMA(
                    self.data.close, period=input_sma_period
                )
                ppo_input = self.input_sma
            self.ppo = indicator_cls(
                ppo_input,
                period1=period1,
                period2=period2,
                period_signal=period_signal,
            )

        def stop(self):
            result["minperiod"] = self.ppo._minperiod
            result["ma1"] = [float(value) for value in self.ppo.ma1.array]
            result["ma2"] = [float(value) for value in self.ppo.ma2.array]
            result["ppo"] = [float(value) for value in self.ppo.lines.ppo.array]
            result["signal"] = [
                float(value) for value in self.ppo.lines.signal.array
            ]
            result["histo"] = [float(value) for value in self.ppo.lines.histo.array]
            if input_sma_period is not None:
                result["input_sma"] = [
                    float(value) for value in self.input_sma.array
                ]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(PPOProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _new_ppo_once_probe(ma1, ma2, period_signal=4, minperiod=1):
    size = len(ma1)
    return SimpleNamespace(
        ma1=SimpleNamespace(lines=[SimpleNamespace(array=list(ma1))]),
        ma2=SimpleNamespace(lines=[SimpleNamespace(array=list(ma2))]),
        lines=SimpleNamespace(
            ppo=SimpleNamespace(array=[float("nan")] * size),
            signal=SimpleNamespace(array=[float("nan")] * size),
            histo=SimpleNamespace(array=[float("nan")] * size),
        ),
        signal_alpha=2.0 / (period_signal + 1.0),
        signal_alpha1=1.0 - 2.0 / (period_signal + 1.0),
        _minperiod=minperiod,
        _long=True,
    )


def _sma(values, period):
    """Calculate a rolling SMA while retaining NaNs in incomplete windows."""
    result = [float("nan")] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        if not any(math.isnan(value) for value in window):
            result[index] = sum(window) / period
    return result


def _ema(values, period, first_valid=0):
    """Calculate an EMA from its first valid period-sized SMA seed."""
    result = [float("nan")] * len(values)
    seed_index = first_valid + period - 1
    if len(values) <= seed_index:
        return result

    previous = sum(values[first_valid : seed_index + 1]) / period
    result[seed_index] = previous
    alpha = 2.0 / (period + 1.0)
    alpha1 = 1.0 - alpha
    for index in range(seed_index + 1, len(values)):
        previous = previous * alpha1 + values[index] * alpha
        result[index] = previous
    return result


def _reference_ppo(
    indicator_cls, prices, period1, period2, period_signal, input_sma_period=None
):
    source = _sma(prices, input_sma_period) if input_sma_period else prices
    first_valid = input_sma_period - 1 if input_sma_period else 0
    ma1 = _ema(source, period1, first_valid)
    ma2 = _ema(source, period2, first_valid)
    ppo = [float("nan")] * len(prices)
    signal = [float("nan")] * len(prices)
    histo = [float("nan")] * len(prices)
    use_long_denominator = indicator_cls is btind.PercentagePriceOscillator
    signal_alpha = 2.0 / (period_signal + 1.0)
    signal_alpha1 = 1.0 - signal_alpha
    previous_signal = None

    for index, (short_ma, long_ma) in enumerate(zip(ma1, ma2)):
        if math.isnan(short_ma) or math.isnan(long_ma):
            continue

        denominator = long_ma if use_long_denominator else short_ma
        current_ppo = (
            100.0 * (short_ma - long_ma) / denominator if denominator else 0.0
        )
        ppo[index] = current_ppo
        if previous_signal is None:
            previous_signal = current_ppo
        else:
            previous_signal = (
                previous_signal * signal_alpha1 + current_ppo * signal_alpha
            )
        signal[index] = previous_signal
        histo[index] = current_ppo - previous_signal

    return {"ppo": ppo, "signal": signal, "histo": histo}


def _assert_line_matches(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if not math.isnan(expected_value):
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            )


@pytest.mark.parametrize(
    "indicator_cls,period1,period2,period_signal",
    [
        (btind.PercentagePriceOscillator, 3, 6, 4),
        (btind.PercentagePriceOscillator, 6, 3, 2),
        (btind.PercentagePriceOscillatorShort, 5, 3, 7),
    ],
)
def test_ppo_runnext_and_runonce_match_independent_full_sequence(
    indicator_cls, period1, period2, period_signal
):
    prices = _prices(40)
    expected = _reference_ppo(
        indicator_cls, prices, period1, period2, period_signal
    )
    runnext = _run_ppo(
        indicator_cls, prices, period1, period2, period_signal, runonce=False
    )
    runonce = _run_ppo(
        indicator_cls, prices, period1, period2, period_signal, runonce=True
    )

    assert runnext["minperiod"] == runonce["minperiod"] == max(period1, period2)
    seed_index = max(period1, period2) - 1
    assert runnext["signal"][seed_index] == pytest.approx(
        runnext["ppo"][seed_index]
    )
    assert runonce["signal"][seed_index] == pytest.approx(
        runonce["ppo"][seed_index]
    )
    assert runonce["histo"][seed_index] == pytest.approx(0.0)
    for line_name in ("ppo", "signal", "histo"):
        _assert_line_matches(runnext[line_name], expected[line_name])
        _assert_line_matches(runonce[line_name], expected[line_name])


@pytest.mark.parametrize("length", [1, 5, 6])
def test_ppo_short_history_preserves_warmup_and_first_valid_seed(length):
    period1, period2, period_signal = 3, 6, 4
    prices = _prices(length)
    expected = _reference_ppo(
        btind.PercentagePriceOscillator,
        prices,
        period1,
        period2,
        period_signal,
    )
    runnext = _run_ppo(
        btind.PercentagePriceOscillator,
        prices,
        period1,
        period2,
        period_signal,
        runonce=False,
    )
    runonce = _run_ppo(
        btind.PercentagePriceOscillator,
        prices,
        period1,
        period2,
        period_signal,
        runonce=True,
    )

    assert runnext["minperiod"] == runonce["minperiod"] == period2
    if length == period2:
        seed_index = period2 - 1
        assert runnext["signal"][seed_index] == pytest.approx(
            runnext["ppo"][seed_index]
        )
        assert runonce["signal"][seed_index] == pytest.approx(
            runonce["ppo"][seed_index]
        )
        assert runonce["histo"][seed_index] == pytest.approx(0.0)
    for line_name in ("ppo", "signal", "histo"):
        _assert_line_matches(runnext[line_name], expected[line_name])
        _assert_line_matches(runonce[line_name], expected[line_name])


def test_ppo_nan_gap_matches_full_runnext_and_runonce_sequences():
    """A missing input poisons both EMA and PPO recursive outputs in both modes."""
    prices = _prices(24)
    gap_index = 9
    prices[gap_index] = float("nan")
    expected = _reference_ppo(
        btind.PercentagePriceOscillator, prices, 3, 6, 4
    )
    runnext = _run_ppo(
        btind.PercentagePriceOscillator, prices, 3, 6, 4, runonce=False
    )
    runonce = _run_ppo(
        btind.PercentagePriceOscillator, prices, 3, 6, 4, runonce=True
    )

    _assert_line_matches(runnext["ma1"], _ema(prices, 3))
    _assert_line_matches(runnext["ma2"], _ema(prices, 6))
    _assert_line_matches(runonce["ma1"], _ema(prices, 3))
    _assert_line_matches(runonce["ma2"], _ema(prices, 6))
    for line_name in ("ppo", "signal", "histo"):
        _assert_line_matches(runnext[line_name], expected[line_name])
        _assert_line_matches(runonce[line_name], expected[line_name])
        assert all(math.isnan(value) for value in runnext[line_name][gap_index:])
        assert all(math.isnan(value) for value in runonce[line_name][gap_index:])


def test_ppo_once_adjacent_gap_chunks_preserve_poisoned_state():
    """Splitting once immediately after a NaN must not reseed the signal."""
    ma1 = [10.0, 11.0, 12.0, float("nan"), 13.0, 14.0, 15.0]
    ma2 = [9.0, 9.5, 10.0, float("nan"), 10.5, 11.0, 11.5]
    full = _new_ppo_once_probe(ma1, ma2)
    chunked = _new_ppo_once_probe(ma1, ma2)

    btind.PercentagePriceOscillator.once(full, 0, len(ma1))
    for start, end in ((0, 3), (3, 4), (4, len(ma1))):
        btind.PercentagePriceOscillator.once(chunked, start, end)

    for line_name in ("ppo", "signal", "histo"):
        _assert_line_matches(
            getattr(chunked.lines, line_name).array,
            getattr(full.lines, line_name).array,
        )
    assert all(math.isnan(value) for value in full.lines.signal.array[3:])


def test_ppo_over_sma_matches_reference_and_chunked_once():
    """A real SMA input preserves its warmup index through EMA and PPO once."""
    prices = _prices(36)
    input_sma_period, period1, period2, period_signal = 4, 3, 6, 5
    first_valid = input_sma_period + max(period1, period2) - 2
    expected = _reference_ppo(
        btind.PercentagePriceOscillator,
        prices,
        period1,
        period2,
        period_signal,
        input_sma_period=input_sma_period,
    )
    runnext = _run_ppo(
        btind.PercentagePriceOscillator,
        prices,
        period1,
        period2,
        period_signal,
        runonce=False,
        input_sma_period=input_sma_period,
    )
    runonce = _run_ppo(
        btind.PercentagePriceOscillator,
        prices,
        period1,
        period2,
        period_signal,
        runonce=True,
        input_sma_period=input_sma_period,
    )

    expected_sma = _sma(prices, input_sma_period)
    expected_ma1 = _ema(expected_sma, period1, input_sma_period - 1)
    expected_ma2 = _ema(expected_sma, period2, input_sma_period - 1)
    expected_minperiod = input_sma_period + max(period1, period2) - 1
    for result in (runnext, runonce):
        assert result["minperiod"] == expected_minperiod
        _assert_line_matches(result["input_sma"], expected_sma)
        _assert_line_matches(result["ma1"], expected_ma1)
        _assert_line_matches(result["ma2"], expected_ma2)
        for line_name in ("ppo", "signal", "histo"):
            _assert_line_matches(result[line_name], expected[line_name])
        assert all(math.isnan(value) for value in result["ppo"][:first_valid])
        assert result["signal"][first_valid] == pytest.approx(
            result["ppo"][first_valid]
        )
        assert result["histo"][first_valid] == pytest.approx(0.0)

    full = _new_ppo_once_probe(
        runonce["ma1"], runonce["ma2"], period_signal, expected_minperiod
    )
    chunked = _new_ppo_once_probe(
        runonce["ma1"], runonce["ma2"], period_signal, expected_minperiod
    )
    btind.PercentagePriceOscillator.once(full, first_valid, len(prices))
    boundaries = (first_valid, first_valid + 1, first_valid + 4, len(prices))
    for start, end in zip(boundaries, boundaries[1:]):
        btind.PercentagePriceOscillator.once(chunked, start, end)
    for line_name in ("ppo", "signal", "histo"):
        values = getattr(chunked.lines, line_name).array
        _assert_line_matches(values, expected[line_name])
        _assert_line_matches(
            values, getattr(full.lines, line_name).array
        )


def test_ppo_nan_in_first_ema_seed_window_propagates_in_histo():
    """nextstart uses the PPO-minus-signal formula when the seed is NaN."""
    prices = _prices(18)
    prices[3] = float("nan")
    runnext = _run_ppo(
        btind.PercentagePriceOscillator, prices, 3, 6, 4, runonce=False
    )
    runonce = _run_ppo(
        btind.PercentagePriceOscillator, prices, 3, 6, 4, runonce=True
    )
    first_valid = max(3, 6) - 1

    for line_name in ("ppo", "signal", "histo"):
        _assert_line_matches(runnext[line_name], runonce[line_name])
        assert all(math.isnan(value) for value in runnext[line_name][first_valid:])
        assert all(math.isnan(value) for value in runonce[line_name][first_valid:])

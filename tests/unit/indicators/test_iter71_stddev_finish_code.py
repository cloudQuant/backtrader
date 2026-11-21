"""In-place replacement of _finish code retains the old invocation path."""

import types

import backtrader as bt
import backtrader.indicators.deviation as deviation
import backtrader.parameters as parameters
import pytest

from .test_iter71_numeric_acceptance_regressions import _indicator


# The replacement code executes with backtrader.parameters' globals.
_r71_stddev_probe = {}


@pytest.mark.parametrize("period", [20, 64])
@pytest.mark.parametrize("behavior", ["return", "raise"])
def test_replaced_finish_code_is_called(monkeypatch, period, behavior):
    indicator = _indicator(bt.ind.StandardDeviation, period, 100)
    function = bt.ind.StandardDeviation._finish

    def returning(_self, _meansq, _mean):
        return 42.0

    def raising(_self, _meansq, _mean):
        raise RuntimeError("changed finish code")

    monkeypatch.setattr(function, "__code__", (returning if behavior == "return" else raising).__code__)
    assert function is deviation._STANDARD_DEVIATION_FINISH
    if behavior == "raise":
        with pytest.raises(RuntimeError, match="changed finish code"):
            indicator.once(0, 100)
    else:
        indicator.once(0, 100)
        assert list(indicator.lines[0].array[period - 1 : 100]) == [42.0] * (101 - period)


def test_original_finish_retains_rolling_optimization(monkeypatch):
    indicator = _indicator(bt.ind.StandardDeviation, 20, 100)
    original = deviation._update_fsum_step
    calls = []

    def observe(*args):
        calls.append(None)
        return original(*args)

    monkeypatch.setattr(deviation, "_update_fsum_step", observe)
    indicator.once(0, 100)
    assert calls


@pytest.mark.parametrize(
    "period,expected",
    [
        (20, [117.5475, 106.54, 107.1875, 107.1875, 106.54, 45930.9475, 45894.81]),
        (64, [117.665771484375, 112.65234375, 115.497802734375, 112.318115234375,
              113.80859375, 112.6162109375, 112.751708984375]),
    ],
)
def test_changed_finish_code_keeps_head_source_mutation_order(monkeypatch, period, expected):
    indicator = _indicator(bt.ind.StandardDeviation, period, 100)
    indicator._code_change_calls = 0

    def mutating(self, meansq, mean):
        self._code_change_calls += 1
        if self._code_change_calls == 5:
            self.data.array[10] = 999.0
        return meansq - mean * mean

    monkeypatch.setattr(bt.ind.StandardDeviation._finish, "__code__", mutating.__code__)
    indicator.once(0, 100)
    assert indicator._code_change_calls == 101 - period
    assert list(indicator.lines[0].array[period - 1 : period + 6]) == pytest.approx(expected)


@pytest.mark.parametrize("period", [20, 64])
@pytest.mark.parametrize("replacement_kind", ["manager_code", "accessor_code", "manager_defaults"])
def test_changed_parameter_reader_keeps_head_source_mutation_order(
    monkeypatch, period, replacement_kind
):
    indicator = _indicator(bt.ind.StandardDeviation, period, 100)
    legacy_calls = []
    original_legacy = deviation._STANDARD_DEVIATION_LEGACY_ROLLING

    def observe_legacy(*args):
        legacy_calls.append(None)
        return original_legacy(*args)

    monkeypatch.setattr(deviation, "_STANDARD_DEVIATION_LEGACY_ROLLING", observe_legacy)
    manager = object.__getattribute__(indicator.p, "_param_manager")
    function = (
        parameters.ParameterAccessor.__getattribute__
        if replacement_kind == "accessor_code"
        else parameters.ParameterManager.get
    )
    original = types.FunctionType(
        function.__code__, function.__globals__, function.__name__,
        function.__defaults__, function.__closure__,
    )
    state = {"calls": 0, "src": indicator.data.array, "original": original}
    monkeypatch.setitem(parameters.__dict__, "_r71_stddev_probe", state)

    def changed_manager(self, name, default=None, _MISSING=None):
        if name == "safepow":
            _r71_stddev_probe["calls"] += 1
            if _r71_stddev_probe["calls"] == 1:
                _r71_stddev_probe["src"][1] = 1000.0
        return _r71_stddev_probe["original"](self, name, default, _MISSING)

    def changed_accessor(self, name):
        if name == "safepow":
            _r71_stddev_probe["calls"] += 1
            if _r71_stddev_probe["calls"] == 1:
                _r71_stddev_probe["src"][1] = 1000.0
        return _r71_stddev_probe["original"](self, name)

    if replacement_kind == "manager_defaults":
        class Descriptor:
            @property
            def default(self):
                state["calls"] += 1
                if state["calls"] == 1:
                    state["src"][1] = 1000.0
                return False

        manager._descriptors["safepow"] = Descriptor()
        manager._value_cache.pop("safepow", None)
        monkeypatch.setattr(function, "__defaults__", (None, True))
    else:
        replacement = changed_accessor if replacement_kind == "accessor_code" else changed_manager
        monkeypatch.setattr(function, "__code__", replacement.__code__)

    indicator.once(0, 100)
    assert legacy_calls == ([None] if period >= 64 else [])
    expected_second = 213.93771874075875 if period == 20 else 10.613780841434403
    assert indicator.lines[0].array[period] == pytest.approx(expected_second)
    assert state["calls"] == (1 if replacement_kind == "manager_defaults" else 101 - period)

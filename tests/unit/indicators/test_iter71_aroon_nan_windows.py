import math
import array
import inspect
import types
from pathlib import Path
import pandas as pd
import pytest
import backtrader as bt
import backtrader.indicators.aroon as module

P = 3
HIGH = [5.0, 7.0, 7.0, 6.0, 9.0, 4.0, 9.0, 3.0, 8.0, 8.0, 2.0, 10.0]
LOW = [3.0, 2.0, 2.0, 4.0, 1.0, 5.0, 1.0, 6.0, 3.0, 3.0, 7.0, 0.0]
VARIANTS = [
    bt.ind.AroonUp,
    bt.ind.AroonDown,
    bt.ind.AroonUpDown,
    bt.ind.AroonOscillator,
    bt.ind.AroonUpDownOscillator,
]


def component(window, highest):
    if len(window) < P + 1 or any(math.isnan(x) for x in window):
        return math.nan
    target = (max if highest else min)(window)
    ago = next(i for i, value in enumerate(reversed(window)) if value == target)
    return 100.0 * (P - ago) / P


def run(indicator, high, low, once, exactbars):
    frame = pd.DataFrame(
        {
            "open": [4.0] * len(high),
            "high": high,
            "low": low,
            "close": [4.0] * len(high),
            "volume": [1.0] * len(high),
        },
        index=pd.date_range("2020-01-01", periods=len(high)),
    )

    class S(bt.Strategy):
        def __init__(self):
            self.ind = indicator(self.data, period=P)
            self.rows = []

        def prenext(self):
            self.next()

        def next(self):
            self.rows.append(
                {
                    name: float(getattr(self.ind.lines, name)[0])
                    for name in self.ind.lines.getlinealiases()
                }
            )

    c = bt.Cerebro(stdstats=False, runonce=once, exactbars=exactbars)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    result = c.run()[0]
    return result.rows, result.ind._minperiod


@pytest.mark.parametrize("indicator", VARIANTS)
@pytest.mark.parametrize("once,exactbars", [(False, 0), (True, 0), (False, 1)])
@pytest.mark.parametrize("side", ["high", "low", "both", "none"])
@pytest.mark.parametrize("missing", [None, 0, 3, 6])
def test_missing_window_and_recovery(indicator, once, exactbars, side, missing):
    assert (
        Path(module.__file__).resolve()
        == (
            Path(__file__).resolve().parents[3] / "backtrader" / "indicators" / "aroon.py"
        ).resolve()
    )
    high, low = HIGH.copy(), LOW.copy()
    if missing is not None:
        if side in ("high", "both"):
            high[missing] = math.nan
        if side in ("low", "both"):
            low[missing] = math.nan
    rows, minperiod = run(indicator, high, low, once, exactbars)
    assert minperiod == P + 1
    assert len(rows) == len(HIGH)
    for index, row in enumerate(rows):
        h = high[max(0, index - P) : index + 1]
        l = low[max(0, index - P) : index + 1]
        up, down = component(h, True), component(l, False)
        expected = {"aroonup": up, "aroondown": down, "aroonosc": up - down}
        for name, actual in row.items():
            wanted = expected[name]
            if math.isnan(wanted):
                assert math.isnan(actual), (index, name, actual, h, l)
            else:
                assert actual == pytest.approx(wanted), (index, name, h, l)


@pytest.mark.parametrize("indicator", VARIANTS)
@pytest.mark.parametrize("once", [False, True])
def test_consecutive_missing(indicator, once):
    high, low = HIGH.copy(), LOW.copy()
    high[3:7] = [math.nan] * 4
    low[3:7] = [math.nan] * 4
    rows, _ = run(indicator, high, low, once, 0)
    for index in range(3, 10):
        assert all(math.isnan(value) for value in rows[index].values())
    assert all(math.isfinite(value) for value in rows[10].values())


@pytest.mark.parametrize("once", [False, True])
def test_exposed_up_down_and_bound_lines(once):
    high, low = HIGH.copy(), LOW.copy()
    high[4], low[6] = math.nan, math.nan

    class Bound(bt.ind.AroonUpDown):
        lines = ("boundup", "bounddown")

        def __init__(self):
            super().__init__()
            self.lines.boundup = self.up
            self.lines.bounddown = self.down

    frame = pd.DataFrame(
        {
            "open": [4.0] * len(high),
            "high": high,
            "low": low,
            "close": [4.0] * len(high),
            "volume": [1.0] * len(high),
        },
        index=pd.date_range("2020-01-01", periods=len(high)),
    )

    class S(bt.Strategy):
        def __init__(self):
            self.ind = Bound(self.data, period=P)
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    len(self.data) - 1,
                    self.ind.up[0],
                    self.ind.down[0],
                    self.ind.boundup[0],
                    self.ind.bounddown[0],
                )
            )

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    rows = c.run()[0].rows
    assert len(rows) == len(HIGH) - P
    for i, up, down, boundup, bounddown in rows:
        for actual, expected in (
            (up, component(high[i - P : i + 1], True)),
            (boundup, component(high[i - P : i + 1], True)),
            (down, component(low[i - P : i + 1], False)),
            (bounddown, component(low[i - P : i + 1], False)),
        ):
            if math.isnan(expected):
                assert math.isnan(actual), (i, actual)
            else:
                assert actual == pytest.approx(expected), (i, actual, expected)


def test_dynamic_getter_and_next_side_effect():
    class Dynamic(bt.ind.AroonUp):
        @property
        def up(self):
            object.__setattr__(self, "_getter_calls", getattr(self, "_getter_calls", 0) + 1)
            return self._user_up

        @up.setter
        def up(self, value):
            object.__setattr__(self, "_user_up", value)

        def next(self):
            object.__setattr__(self, "_next_calls", getattr(self, "_next_calls", 0) + 1)
            super().next()

    rows, _ = run(Dynamic, HIGH, LOW, False, 0)
    assert len(rows) == len(HIGH)

    # Make callback and getter counts observable from the actual instance.
    class S(bt.Strategy):
        def __init__(self):
            self.ind = Dynamic(self.data, period=P)

    frame = pd.DataFrame(
        {
            "open": [4.0] * len(HIGH),
            "high": HIGH,
            "low": LOW,
            "close": [4.0] * len(HIGH),
            "volume": [1.0] * len(HIGH),
        },
        index=pd.date_range("2020-01-01", periods=len(HIGH)),
    )
    c = bt.Cerebro(stdstats=False, runonce=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    ind = c.run()[0].ind
    assert ind._next_calls == len(HIGH) - P
    assert ind._getter_calls == ind._next_calls


@pytest.mark.parametrize("once", [False, True])
def test_secondary_feed_nan_and_clock(once):
    high, low = HIGH.copy(), LOW.copy()
    high[4] = math.nan

    def frame(h, l, freq):
        return pd.DataFrame(
            {
                "open": [4.0] * len(h),
                "high": h,
                "low": l,
                "close": [4.0] * len(h),
                "volume": [1.0] * len(h),
            },
            index=pd.date_range("2020-01-01", periods=len(h), freq=freq),
        )

    class S(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.AroonUp(self.data1, period=P)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data0), len(self.data1), self.ind.aroonup[0]))

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=frame([4.0] * 23, [2.0] * 23, "D")))
    c.adddata(bt.feeds.PandasData(dataname=frame(high, low, "2D")))
    c.addstrategy(S)
    rows = c.run()[0].rows
    assert {slow for _, slow, _ in rows} == set(range(P + 1, len(high) + 1))
    for fast, slow, actual in rows:
        expected = component(high[slow - P - 1 : slow], True)
        if math.isnan(expected):
            assert math.isnan(actual), (fast, slow, actual)
        else:
            assert actual == pytest.approx(expected), (fast, slow, actual, expected)


@pytest.mark.parametrize("highest", [False, True])
@pytest.mark.parametrize("period", [2, 32, 64])
def test_rolling_index_segments_nan_expiry_and_ties(highest, period):
    values = [float((i * 7) % 19) for i in range(200)]
    for i in (0, 7, 31, 63, 64, 127, 180):
        values[i] = math.nan
    source = array.array("d", values)
    destination = array.array("d", [-999.0] * 205)
    segments = [(5, 44), (44, 104), (104, 200), (200, 205)]
    for start, end in segments:
        module._once_missing_index(source, destination, start, end, period, highest)
    assert destination[:5].tolist() == [-999.0] * 5
    for i in range(5, 205):
        if i >= len(values) or i < period - 1:
            assert math.isnan(destination[i])
            continue
        window = values[i - period + 1 : i + 1]
        if any(math.isnan(v) for v in window):
            assert math.isnan(destination[i]), i
        else:
            extreme = (max if highest else min)(window)
            assert destination[i] == next(j for j, v in enumerate(reversed(window)) if v == extreme)


def test_rolling_fast_gate_rejects_invalid_contracts():
    src, dst = array.array("d", [1.0, 2.0]), array.array("d", [0.0, 0.0])
    assert module._rolling_eligible(src, dst, 0, 2, 1)
    for args in (
        (list(src), dst, 0, 2, 1),
        (src, src, 0, 2, 1),
        (src, dst, True, 2, 1),
        (src, dst, 0, 2, False),
        (src, dst, 0, 2, 0),
        (src, dst, -1, 2, 1),
        (src, dst, 2, 1, 1),
        (src, dst, 0.0, 2, 1),
        (src, dst, 0, 2.0, 1),
    ):
        assert not module._rolling_eligible(*args)


def test_long_period_real_cerebro_exercises_both_fast_paths(monkeypatch):
    calls = []
    original = module._once_missing_index

    def observe(src, dst, start, end, period, highest):
        calls.append((inspect.currentframe().f_back.f_code.co_name, period, highest))
        return original(src, dst, start, end, period, highest)

    monkeypatch.setattr(module, "_once_missing_index", observe)
    high = [float((i * 7) % 31) for i in range(170)]
    high[75] = math.nan
    frame = pd.DataFrame(
        {
            "open": [4.0] * 170,
            "high": high,
            "low": [1.0] * 170,
            "close": [4.0] * 170,
            "volume": [1.0] * 170,
        },
        index=pd.date_range("2020-01-01", periods=170),
    )

    class S(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.AroonUp(self.data, period=64)

        def next(self):
            i = len(self.data) - 1
            window = high[i - 64 : i + 1]
            expected = (
                math.nan
                if any(math.isnan(v) for v in window)
                else (
                    100.0
                    * (64 - next(j for j, v in enumerate(reversed(window)) if v == max(window)))
                    / 64
                )
            )
            got = self.ind.aroonup[0]
            assert math.isnan(got) if math.isnan(expected) else got == pytest.approx(expected)

    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    c.run()
    assert ("once", 65, True) in calls, calls
    assert ("_once_line", 65, True) in calls, calls


def test_dynamic_extrema_subclass_and_func_use_generic_path(monkeypatch):
    calls = []
    original = module._once_missing_index

    def observe(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(module, "_once_missing_index", observe)
    used = []

    class Custom(module._AroonHighest):
        def func(self, iterable):
            used.append(1)
            return 7.0

    class S(bt.Strategy):
        def __init__(self):
            self.ind = Custom(self.data.high, period=32)

        def next(self):
            assert self.ind[0] == 7.0

    frame = pd.DataFrame(
        {
            "open": [4.0] * 80,
            "high": [4.0] * 80,
            "low": [1.0] * 80,
            "close": [4.0] * 80,
            "volume": [1.0] * 80,
        },
        index=pd.date_range("2020-01-01", periods=80),
    )
    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    c.run()
    assert used and not calls


@pytest.mark.parametrize("mode", ["func", "evalfunc"])
def test_dynamic_exact_extrema_instance_falls_back(monkeypatch, mode):
    calls, used = [], []
    original = module._once_missing_index

    def observe(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(module, "_once_missing_index", observe)

    class S(bt.Strategy):
        def __init__(self):
            self.ind = module._AroonHighest(self.data.high, period=32)
            if mode == "func":

                def custom(values):
                    used.append(1)
                    return 7.0

                self.ind.func = custom
            else:

                def custom(values):
                    used.append(1)
                    return min(values)

                self.ind.p._evalfunc = custom

        def next(self):
            assert self.ind[0] == (7.0 if mode == "func" else 0.0)

    frame = pd.DataFrame(
        {
            "open": [4.0] * 80,
            "high": [4.0] * 80,
            "low": [1.0] * 80,
            "close": [4.0] * 80,
            "volume": [1.0] * 80,
        },
        index=pd.date_range("2020-01-01", periods=80),
    )
    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    c.run()
    assert used and not calls


def test_dynamic_aroon_index_subclass_callback_not_skipped(monkeypatch):
    used = []

    class Custom(bt.ind.AroonUp):
        @staticmethod
        def _index_since_extreme(source, index, period, highest):
            used.append(index)
            return 1

    rows, _ = run(Custom, HIGH, LOW, True, 0)
    assert used
    assert all(row["aroonup"] == pytest.approx(100.0 * (P - 1) / P) for row in rows[P:])


def test_dynamic_aroon_index_descriptor_read_count(monkeypatch):
    calls = []

    class Descriptor:
        def __get__(self, instance, owner):
            calls.append(1)
            return lambda source, index, period, highest: 1

    monkeypatch.setattr(bt.ind.AroonUp, "_index_since_extreme", Descriptor())
    rows, _ = run(bt.ind.AroonUp, HIGH, LOW, True, 0)
    assert len(calls) == len(HIGH) - P
    assert all(row["aroonup"] == pytest.approx(100.0 * (P - 1) / P) for row in rows[P:])


def _one_extrema():
    class S(bt.Strategy):
        def __init__(self):
            self.ind = module._AroonHighest(self.data.high, period=2)

    frame = pd.DataFrame(
        {
            "open": [1.0] * 6,
            "high": [2.0] * 6,
            "low": [1.0] * 6,
            "close": [1.0] * 6,
            "volume": [1.0] * 6,
        },
        index=pd.date_range("2020-01-01", periods=6),
    )
    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    return c.run()[0].ind


@pytest.mark.parametrize("raises", [False, True])
def test_fallback_dynamic_source_read_once(raises):
    ind = _one_extrema()

    class Source:
        calls = 0

        @property
        def array(self):
            self.calls += 1
            if raises:
                raise ValueError("probe")
            return [1.0, 2.0]

    source = Source()
    object.__setattr__(ind, "data", source)
    ind.once(0, 0)
    assert source.calls == 1


@pytest.mark.parametrize("value", [False, 0, 1.5, "invalid", None])
def test_fallback_dynamic_period_read_once(value):
    ind = _one_extrema()
    manager = ind.p._param_manager
    original = manager.get
    calls = []

    def dynamic(name, *args):
        if name == "period":
            calls.append(1)
            return value
        return original(name, *args)

    manager.get = dynamic
    ind.once(0, 0)
    assert len(calls) == 1


def test_unsafe_speculative_reads_reproduce_double_calls(monkeypatch):
    ind = _one_extrema()

    class Source:
        calls = 0

        @property
        def array(self):
            self.calls += 1
            return [1.0, 2.0]

    source = Source()
    object.__setattr__(ind, "data", source)
    assert module._plain_aroon(ind, max)

    def unsafe(indicator, start, end):
        src, dst, period = indicator.data.array, indicator.lines[0].array, indicator.p.period
        return (
            (src, dst, period) if module._rolling_eligible(src, dst, start, end, period) else None
        )

    with monkeypatch.context() as context:
        context.setattr(module, "_safe_rolling_inputs", unsafe)
        ind.once(0, 0)
    assert source.calls == 2
    source.calls = 0
    ind.once(0, 0)
    assert source.calls == 1


def test_unsafe_speculation_changes_exception_behavior(monkeypatch):
    ind = _one_extrema()

    class Source:
        calls = 0

        @property
        def array(self):
            self.calls += 1
            raise ValueError("source sentinel")

    source = Source()
    object.__setattr__(ind, "data", source)

    def unsafe(indicator, start, end):
        indicator.data.array

    with monkeypatch.context() as context:
        context.setattr(module, "_safe_rolling_inputs", unsafe)
        with pytest.raises(ValueError, match="source sentinel"):
            ind.once(0, 0)
    source.calls = 0
    ind.once(0, 0)
    assert source.calls == 1


def collision_observation(location, force_fallback):
    ind = _one_extrema()
    manager = ind.p._param_manager

    class Key:
        def __init__(self, target):
            self.target = target
            self.calls = []

        def __hash__(self):
            return hash(self.target)

        def __eq__(self, other):
            self.calls.append(other)
            return type(other) is str and other == self.target

    if location in ("_values", "_descriptors", "_lazy_defaults"):
        target, state = "period", getattr(manager, location)
        replacement = state.get(target, None)
    elif location == "manager":
        target, state, replacement = "get", vars(manager), manager.get
    elif location == "source":
        target, state, replacement = "array", vars(ind.data), ind.data.array
    elif location == "destination":
        target, state, replacement = "array", vars(ind.lines[0]), ind.lines[0].array
    elif location == "lines":
        target, state, replacement = "lines", vars(ind.lines), ind.lines.lines
    else:
        raise AssertionError(location)
    state.pop(target, None)
    key = Key(target)
    state[key] = replacement
    key.calls.clear()
    old = module._safe_rolling_inputs
    if force_fallback:
        module._safe_rolling_inputs = lambda *args: None
    try:
        ind.once(0, 0)
    finally:
        module._safe_rolling_inputs = old
    return key.calls


@pytest.mark.parametrize(
    "location",
    ["_values", "_descriptors", "_lazy_defaults", "manager", "source", "destination", "lines"],
)
def test_fallback_does_not_add_colliding_key_comparisons(location):
    expected = collision_observation(location, True)
    actual = collision_observation(location, False)
    assert actual == expected


@pytest.mark.parametrize("location", ["_values", "_descriptors", "manager"])
def test_raising_collision_preserves_exception_behavior(location):
    def observe(force_fallback):
        ind = _one_extrema()
        manager = ind.p._param_manager
        target = "get" if location == "manager" else "period"
        state = vars(manager) if location == "manager" else getattr(manager, location)
        replacement = manager.get if location == "manager" else state[target]
        state.pop(target, None)

        class Key:
            calls = 0

            def __hash__(self):
                return hash(target)

            def __eq__(self, other):
                self.calls += 1
                raise ValueError("comparison sentinel")

        key = Key()
        state[key] = replacement
        old = module._safe_rolling_inputs
        if force_fallback:
            module._safe_rolling_inputs = lambda *args: None
        try:
            try:
                ind.once(0, 0)
                result = None
            except Exception as exc:
                result = type(exc)
        finally:
            module._safe_rolling_inputs = old
        return key.calls, result

    assert observe(False) == observe(True)


def test_parameter_get_code_mutation_preserves_value_and_calls(monkeypatch):
    ind = _one_extrema()
    ind.data.array[:] = array.array("d", [1.0, 2.0, 1.0, 2.0, 1.0, 2.0])
    func = module.ParameterManager.get
    original = types.FunctionType(
        func.__code__, func.__globals__, argdefs=func.__defaults__, closure=func.__closure__
    )
    namespace = func.__globals__
    calls = []
    monkeypatch.setitem(namespace, "_iter71_original_get", original)
    monkeypatch.setitem(namespace, "_iter71_period_reads", calls)

    def dynamic(self, name, default=None, _MISSING=None):
        if name == "period":
            _iter71_period_reads.append(name)  # noqa: F821
            return 1
        return _iter71_original_get(self, name, default)  # noqa: F821

    original_code = func.__code__
    try:
        func.__code__ = dynamic.__code__
        assert module._safe_rolling_inputs(ind, 1, 6) is None
        ind.once(1, 6)
        actual = list(ind.lines[0].array[1:6])
        assert calls == ["period"]
        assert actual == [0.0] * 5
    finally:
        func.__code__ = original_code
    assert module._safe_rolling_inputs(ind, 1, 6) is not None


def test_parameter_get_default_mutation_disables_fast_path():
    ind = _one_extrema()
    func = module.ParameterManager.get
    original = func.__defaults__
    try:
        func.__defaults__ = (None, 2)
        assert module._safe_rolling_inputs(ind, 1, 6) is None
    finally:
        func.__defaults__ = original
    assert module._safe_rolling_inputs(ind, 1, 6) is not None


def test_accessor_getattribute_code_mutation_disables_fast_path():
    ind = _one_extrema()
    func = module._ACCESSOR_GETATTRIBUTE

    def dynamic(self, name):
        return None

    original = func.__code__
    try:
        func.__code__ = dynamic.__code__
        assert not module._plain_aroon(ind, max)
    finally:
        func.__code__ = original
    assert module._plain_aroon(ind, max)


def test_accessor_direct_attrs_mutation_keeps_period_lookup(monkeypatch):
    ind = _one_extrema()
    ind.data.array[:] = array.array("d", [1.0, 2.0, 1.0, 2.0, 1.0, 2.0])
    params = ind.p
    object.__setattr__(params, "period", 1)
    namespace = module._ACCESSOR_GETATTRIBUTE.__globals__
    with monkeypatch.context() as context:
        context.setitem(
            namespace,
            "_PARAMETER_ACCESSOR_DIRECT_ATTRS",
            module._ACCESSOR_DIRECT_ATTRS | {"period"},
        )
        assert not module._plain_aroon(ind, max)
        ind.once(1, 6)
        assert list(ind.lines[0].array[1:6]) == [0.0] * 5
    assert module._plain_aroon(ind, max)


def test_missing_aware_func_code_mutation_keeps_callback():
    ind = _one_extrema()
    func = module._MISSING_AWARE_FUNC

    class Replacement:
        def method(self, iterable):
            if False:
                super()
            return 1

    original = func.__code__
    try:
        func.__code__ = Replacement.method.__code__
        ind.once(1, 6)
        assert list(ind.lines[0].array[1:6]) == [1.0] * 5
    finally:
        func.__code__ = original


def test_lines_getitem_code_mutation_disables_fast_path():
    ind = _one_extrema()
    func = module._LINES_GETITEM

    def dynamic(self, index):
        return None

    original = func.__code__
    try:
        func.__code__ = dynamic.__code__
        assert module._safe_rolling_inputs(ind, 1, 6) is None
    finally:
        func.__code__ = original
    assert module._safe_rolling_inputs(ind, 1, 6) is not None


def test_findfirst_code_mutation_keeps_callback(monkeypatch):
    ind = _one_extrema()
    func = module._FIND_FIRST_FUNC
    original = func.__code__
    calls = []
    namespace = func.__globals__
    monkeypatch.setitem(namespace, "_iter71_index_reads", calls)

    def dynamic(self, iterable):
        _iter71_index_reads.append(1)  # noqa: F821
        return 1

    try:
        func.__code__ = dynamic.__code__
        ind.once(1, 6)
        assert calls == [1] * 5
        assert list(ind.lines[0].array[1:6]) == [1.0] * 5
    finally:
        func.__code__ = original


def test_aroon_window_code_mutation_keeps_callback():
    func = module._AROON_INDEX_DESCRIPTOR.__func__
    original = func.__code__

    def dynamic(source, index, period, highest):
        return 1

    try:
        func.__code__ = dynamic.__code__
        rows, _ = run(bt.ind.AroonUp, HIGH, LOW, True, 0)
        assert all(row["aroonup"] == pytest.approx(100.0 * (P - 1) / P) for row in rows[P:])
    finally:
        func.__code__ = original

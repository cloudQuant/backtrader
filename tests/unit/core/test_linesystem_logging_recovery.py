"""Regression coverage for line-system logging recovery paths.

Missing attributes and incomplete clocks are expected EAFP/protocol probes in
the line system.  They must remain quiet even when DEBUG logging is enabled.
The few branches that intentionally preserve a numeric fallback for an
unexpected exception instead produce bounded WARNING diagnostics.
"""

import builtins
import logging
from types import SimpleNamespace

import pytest

import backtrader as bt
import backtrader.linebuffer as linebuffer_module
import backtrader.lineiterator as lineiterator_module
import backtrader.lineroot as lineroot_module
import backtrader.lineseries as lineseries_module
import backtrader.strategy as strategy_module
from backtrader.utils import log_message


class RecordingHandler(logging.Handler):
    """Keep emitted records in memory without formatting third-party values."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _install_logger(monkeypatch, module, level):
    logger = logging.Logger(module.__name__, level)
    handler = RecordingHandler()
    logger.addHandler(handler)
    monkeypatch.setattr(module, "logger", logger)
    return handler


def _formatted_records(records):
    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    return [formatter.format(record) for record in records]


def _assert_safe_records(records):
    rendered = _formatted_records(records)
    text = "\n".join(rendered)
    assert "synthetic-secret" not in text
    assert "Traceback" not in text
    assert all(not record.exc_info for record in records)
    return rendered


def _assert_bounded_records(handler, key, level=logging.WARNING, expected_total=250):
    assert len(handler.records) == 3
    assert all(record.levelno == level for record in handler.records)
    assert key in "\n".join(_assert_safe_records(handler.records))
    states = [
        state
        for (
            _name,
            state_key,
            _level,
            _exception_type,
        ), state in log_message._throttle_state.items()
        if state_key == key
    ]
    assert len(states) == 1
    assert states[0]["total"] == expected_total
    assert states[0]["count"] == 49


@pytest.fixture(autouse=True)
def _reset_logging_state():
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)
    yield
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)


class _ActionWithoutDependencies:
    _clock = lineseries_module.MinimalClock()


class _Unsized:
    def __len__(self):
        raise TypeError("optional length is unavailable")


class _OwnerWithoutLength:
    datas = [_Unsized()]

    def __len__(self):
        raise TypeError("owner length is unavailable")


class _ClockProbe:
    datas = []
    _clock = _Unsized()

    def __len__(self):
        return 0


class _ClockProbeWithOwner(_ClockProbe):
    _owner = _OwnerWithoutLength()


class _NextProbe:
    """A slotted Strategy-shaped object that rejects the status cache."""

    __slots__ = ("_ltype", "datas", "_lineiterators", "phase")

    def __init__(self):
        self._ltype = lineiterator_module.LineIterator.StratType
        self.datas = []
        self._lineiterators = {lineiterator_module.LineIterator.IndType: []}
        self.phase = None

    def _clk_update(self):
        return 0

    def _notify(self):
        return None

    def _getminperstatus(self):
        return 1

    def prenext(self):
        self.phase = "prenext"


class _LineWithoutLengthCount:
    array = [0.0]


class _UntruthyLines:
    def __bool__(self):
        raise TypeError("line list cannot be inspected")


class _BrokenDateTime:
    def __getitem__(self, index):
        raise IndexError("datetime not populated")


class _BadDatetimeData:
    datetime = _BrokenDateTime()

    def __len__(self):
        return 1


class _ClockParent:
    def _clk_update(self):
        return 1


class _OldSyncDatetimeProbe(_ClockParent):
    _oldsync = True
    datas = [_BadDatetimeData()]

    def __init__(self):
        self.lines = SimpleNamespace(datetime=[0.0])


class _NormalDatetimeProbe:
    _oldsync = False
    datas = [_BadDatetimeData()]

    def __init__(self):
        self._dlens = [0]
        self.lines = SimpleNamespace(datetime=[0.0])

    def __len__(self):
        return 1


class _ExplodingDescriptor:
    def __get__(self, instance, owner):
        raise AttributeError("descriptor has no value")


class _DescriptorLines(lineseries_module.Lines):
    exploding = _ExplodingDescriptor()


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_repeated_expected_line_protocol_probes_stay_silent(monkeypatch, level):
    """Expected EAFP probes never create diagnostic records at DEBUG or INFO."""
    iterator_handler = _install_logger(monkeypatch, lineiterator_module, level)
    root_handler = _install_logger(monkeypatch, lineroot_module, level)
    series_handler = _install_logger(monkeypatch, lineseries_module, level)

    for _ in range(250):
        assert lineiterator_module._lineaction_source_clock(_ActionWithoutDependencies()) is None
        assert lineiterator_module.LineIterator._clk_update(_ClockProbe()) == 0
        assert lineiterator_module.LineIterator._clk_update(_ClockProbeWithOwner()) == 0

        next_probe = _NextProbe()
        lineiterator_module.LineIterator._next(next_probe)
        assert next_probe.phase == "prenext"

        iterator = object.__new__(lineiterator_module.LineIterator)
        line = _LineWithoutLengthCount()
        object.__setattr__(iterator, "_cached_first_line", line)
        object.__setattr__(iterator, "lines", SimpleNamespace(lines=[line]))
        assert lineiterator_module.LineIterator.__len__(iterator) == 1

        unsized_iterator = object.__new__(lineiterator_module.LineIterator)
        object.__setattr__(unsized_iterator, "lines", SimpleNamespace(lines=_UntruthyLines()))
        assert lineiterator_module.LineIterator.__len__(unsized_iterator) == 0

        empty_lines = object.__new__(lineseries_module.Lines)
        assert lineseries_module.Lines.__getattr__(empty_lines, "_clock") is None
        with pytest.raises(AttributeError):
            getattr(empty_lines, "missing")

        descriptor_lines = object.__new__(_DescriptorLines)
        with pytest.raises(AttributeError):
            getattr(descriptor_lines, "exploding")

        populated_lines = object.__new__(lineseries_module.Lines)
        object.__setattr__(populated_lines, "lines", object())
        with pytest.raises(AttributeError):
            getattr(populated_lines, "missing")

        data_alias = object.__new__(lineseries_module.LineSeries)
        assert isinstance(getattr(data_alias, "data0"), lineseries_module.MinimalData)

        owner_alias = object.__new__(lineseries_module.LineSeries)
        object.__setattr__(owner_alias, "_owner", object())
        assert isinstance(getattr(owner_alias, "data0"), lineseries_module.MinimalData)

        with_lines = object.__new__(lineseries_module.LineSeries)
        object.__setattr__(with_lines, "lines", object())
        with pytest.raises(AttributeError):
            getattr(with_lines, "missing")

        without_lines = object.__new__(lineseries_module.LineSeries)
        with pytest.raises(AttributeError):
            getattr(without_lines, "missing")

    # The legacy strategy patch closures are explicitly exercised because they
    # remain compatibility paths even though normal Strategy dispatch may use
    # a later implementation.
    class RootPatchTarget:
        pass

    monkeypatch.setattr(strategy_module, "Strategy", RootPatchTarget)
    lineroot_module._apply_strategy_patch()
    for _ in range(250):
        probe = _OldSyncDatetimeProbe()
        assert RootPatchTarget._clk_update(probe) == 1
        assert probe.lines.datetime[0] == 1.0

        normal_probe = _NormalDatetimeProbe()
        assert RootPatchTarget._clk_update(normal_probe) == 1
        assert normal_probe.lines.datetime[0] == 1.0

    class SeriesPatchTarget:
        pass

    monkeypatch.setattr(strategy_module, "Strategy", SeriesPatchTarget)
    assert lineseries_module._patch_strategy_clk_update() is True
    for _ in range(250):
        probe = _OldSyncDatetimeProbe()
        assert SeriesPatchTarget._clk_update(probe) == 1
        assert probe.lines.datetime[0] == 1.0

    assert iterator_handler.records == []
    assert root_handler.records == []
    assert series_handler.records == []


class _BrokenLines:
    def __getitem__(self, index):
        raise RuntimeError("synthetic-secret")


class _BrokenArray:
    def __len__(self):
        raise RuntimeError("synthetic-secret")


class _BrokenLine:
    array = _BrokenArray()


class _FailingClockParent:
    def _clk_update(self):
        raise RuntimeError("synthetic-secret")


class _FailingOldSyncProbe(_FailingClockParent):
    _oldsync = True


class _BrokenLengthData:
    def __len__(self):
        raise RuntimeError("synthetic-secret")


class _DataLengthRecoveryProbe:
    _oldsync = False
    datas = [_BrokenLengthData()]

    def __init__(self):
        self._dlens = [0]

    def __len__(self):
        return 7


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_repeated_line_recoveries_are_bounded_and_keep_fallback_values(monkeypatch, level):
    """Recovery branches retain legacy values while warning only at bounded volume."""
    iterator_handler = _install_logger(monkeypatch, lineiterator_module, level)
    series_handler = _install_logger(monkeypatch, lineseries_module, level)
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(log_message, "_throttle_enabled", True)

    series_length = object.__new__(lineseries_module.LineSeries)
    object.__setattr__(series_length, "lines", _BrokenLines())
    series_item = object.__new__(lineseries_module.LineSeries)
    object.__setattr__(series_item, "lines", _BrokenLines())

    iterator = object.__new__(lineiterator_module.LineIterator)
    broken_line = _BrokenLine()
    object.__setattr__(iterator, "lines", SimpleNamespace(lines=[broken_line]))

    class SeriesPatchTarget:
        pass

    monkeypatch.setattr(strategy_module, "Strategy", SeriesPatchTarget)
    assert lineseries_module._patch_strategy_clk_update() is True

    for _ in range(250):
        assert lineseries_module.LineSeries.__len__(series_length) == 0
        assert lineseries_module.LineSeries.__getitem__(series_item, 0) == 0.0
        assert lineiterator_module.LineIterator.__len__(iterator) == 0
        assert SeriesPatchTarget._clk_update(_FailingOldSyncProbe()) == 1
        assert SeriesPatchTarget._clk_update(_DataLengthRecoveryProbe()) == 7

    records = iterator_handler.records + series_handler.records
    messages = _assert_safe_records(records)
    assert len(records) == 15
    assert len(iterator_handler.records) == 3
    assert len(series_handler.records) == 12
    assert all(
        "recovery" in message.lower() or "repeated" in message.lower() for message in messages
    )

    states = list(log_message._throttle_state.values())
    assert len(states) == 5
    assert all(state["total"] == 250 and state["count"] == 49 for state in states)
    assert {state_key[1] for state_key in log_message._throttle_state} == {
        "lineiterator_length_recovery",
        "lineseries_length_recovery",
        "lineseries_item_recovery",
        "lineseries_strategy_clock_oldsync_recovery",
        "lineseries_strategy_clock_data_length_recovery",
    }


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_assignment_minperiod_recovery_is_bounded_and_redacted(monkeypatch, level):
    """A malformed owner retains its period without leaking a rejected update error."""

    class BrokenOwner:
        _minperiod = 3

        def updateminperiod(self, _period):
            raise RuntimeError("synthetic-secret")

    class Child:
        _minperiod = 5

    handler = _install_logger(monkeypatch, lineseries_module, level)
    owner = BrokenOwner()
    for _ in range(250):
        assert lineseries_module._propagate_assignment_minperiod(owner, Child()) is None

    assert owner._minperiod == 3
    _assert_bounded_records(handler, "lineseries.assignment_minperiod.propagation_recovery")


class _BrokenClock:
    def __len__(self):
        raise RuntimeError("synthetic-secret")


@pytest.mark.parametrize(
    ("factory", "forward", "key"),
    [
        (
            lambda line: _make_lines(line),
            lambda container: lineseries_module.Lines.forward(container),
            "lineseries.lines.forward.clock_length_recovery",
        ),
        (
            lambda line: _make_lineseries(line),
            lambda container: lineseries_module.LineSeries.forward(container),
            "lineseries.lineseries.forward.clock_length_recovery",
        ),
    ],
)
@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_forward_clock_recoveries_are_bounded_and_keep_advancing(
    monkeypatch, level, factory, forward, key
):
    """Clock failures retain the existing forward behavior without traceback data."""
    handler = _install_logger(monkeypatch, lineseries_module, level)
    line = linebuffer_module.LineBuffer()
    line._clock = _BrokenClock()
    container = factory(line)

    for _ in range(250):
        forward(container)

    assert line.lencount == 250
    assert len(line.array) == 250
    _assert_bounded_records(handler, key)


def _make_lines(line):
    lines = object.__new__(lineseries_module.Lines)
    object.__setattr__(lines, "lines", [line])
    return lines


def _make_lineseries(line):
    series = object.__new__(lineseries_module.LineSeries)
    object.__setattr__(series, "lines", SimpleNamespace(lines=[line]))
    return series


class _BrokenIterable:
    def __iter__(self):
        raise RuntimeError("synthetic-secret")


class _BrokenLineStorage:
    def __len__(self):
        return 1

    def __setitem__(self, index, value):
        raise RuntimeError("synthetic-secret")


@pytest.mark.parametrize(
    ("value", "key"),
    [
        (_BrokenIterable(), "lineseries.lines.setitem.iterable_failure"),
        (1.0, "lineseries.lines.setitem.assignment_failure"),
    ],
)
def test_lines_setitem_propagates_and_writes_one_safe_file_diagnostic(tmp_path, value, key):
    """Failed line assignment must propagate rather than create an unused side value."""
    lines = object.__new__(lineseries_module.Lines)
    storage = (
        [linebuffer_module.LineBuffer()]
        if isinstance(value, _BrokenIterable)
        else _BrokenLineStorage()
    )
    object.__setattr__(lines, "lines", storage)

    log_file = tmp_path / "line-recovery.log"
    bt.configure_logging(level="DEBUG", console=False, log_file=str(log_file), backend="stdlib")
    for _ in range(250):
        with pytest.raises(RuntimeError, match="synthetic-secret"):
            lines[0] = value
    states = [
        state
        for (
            _name,
            state_key,
            _level,
            _exception_type,
        ), state in log_message._throttle_state.items()
        if state_key == key
    ]
    log_message.reset_logging()

    output = log_file.read_text(encoding="utf-8")
    records = [line for line in output.splitlines() if line.strip()]
    assert len(records) == 3
    assert key in output
    assert "synthetic-secret" not in output
    assert "Traceback" not in output
    assert len(states) == 1
    assert states[0]["total"] == 250
    assert states[0]["count"] == 49


class _BrokenReplayClock:
    @property
    def replaying(self):
        raise RuntimeError("synthetic-secret")


class _BrokenSourceIterator:
    _clock = lineseries_module.MinimalClock()

    @property
    def datas(self):
        raise RuntimeError("synthetic-secret")

    def __len__(self):
        return 0

    def forward(self):
        raise AssertionError("a zero clock must not advance")


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_lineiterator_clock_recoveries_are_bounded_and_keep_safe_values(monkeypatch, level):
    """Replay/source-clock recovery remains visible but never exposes exception data."""
    handler = _install_logger(monkeypatch, lineiterator_module, level)

    for _ in range(250):
        assert lineiterator_module._clock_is_replaying(_BrokenReplayClock()) is False
        assert lineiterator_module.LineIterator._clk_update(_BrokenSourceIterator()) == 0

    assert len(handler.records) == 6
    rendered = _assert_safe_records(handler.records)
    for key in ("clock_replay_flag", "iterator_source_clock"):
        assert key in "\n".join(rendered)
        states = [
            state
            for (
                _name,
                state_key,
                _level,
                _exception_type,
            ), state in log_message._throttle_state.items()
            if state_key == key
        ]
        assert len(states) == 1
        assert states[0]["total"] == 250
        assert states[0]["count"] == 49


class _NoLines:
    pass


class _ValueRoot:
    def __getitem__(self, index):
        return 1.0


class _BrokenLineValue:
    def __len__(self):
        raise RuntimeError("synthetic-secret")

    def __getitem__(self, index):
        return 1.0


class _BrokenLinesValue:
    def __bool__(self):
        return True

    def __len__(self):
        return 1

    def __getitem__(self, index):
        return _BrokenLineValue()


class _BrokenRoot:
    lines = _BrokenLinesValue()


def _broken_operation(*args):
    raise RuntimeError("synthetic-secret")


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_lineroot_safe_fallbacks_are_bounded_and_redacted(monkeypatch, level):
    """Every retained LineRoot fallback uses a fixed, bounded warning."""
    handler = _install_logger(monkeypatch, lineroot_module, level)

    for _ in range(250):
        assert lineroot_module.LineRoot._makeoperation(_NoLines(), 1.0, _broken_operation) == 0
        assert lineroot_module.LineRoot._makeoperationown(_NoLines(), _broken_operation) == 0
        assert (
            lineroot_module.LineRoot._operation_stage2(_ValueRoot(), 1.0, _broken_operation) == 0.0
        )
        assert lineroot_module.LineRoot.__nonzero__(_BrokenRoot()) is False
        assert lineroot_module.LineRoot._makeoperationown(_BrokenRoot(), bool) is False
        assert lineroot_module.LineMultiple._makeoperation(_NoLines(), 1.0, _broken_operation) == 0
        assert lineroot_module.LineMultiple._makeoperationown(_NoLines(), _broken_operation) == 0
        assert lineroot_module.LineMultiple._makeoperationown(_BrokenRoot(), bool) is False

    expected_keys = {
        "lineroot.line_root.makeoperation_recovery",
        "lineroot.line_root.makeoperationown_recovery",
        "lineroot.line_root.operation_stage2_recovery",
        "lineroot.line_root.nonzero_recovery",
        "lineroot.line_root.makeoperationown_boolean_recovery",
        "lineroot.line_multiple.makeoperation_recovery",
        "lineroot.line_multiple.makeoperationown_recovery",
        "lineroot.line_multiple.makeoperationown_boolean_recovery",
    }
    assert len(handler.records) == len(expected_keys) * 3
    rendered = _assert_safe_records(handler.records)
    assert expected_keys <= {
        state_key for (_name, state_key, _level, _exception_type) in log_message._throttle_state
    }
    for key in expected_keys:
        assert key in "\n".join(rendered)
        states = [
            state
            for (
                _name,
                state_key,
                _level,
                _exception_type,
            ), state in log_message._throttle_state.items()
            if state_key == key
        ]
        assert len(states) == 1
        assert states[0]["total"] == 250
        assert states[0]["count"] == 49


def test_lineiterator_unsafe_batch_dependencies_propagate_without_logs(monkeypatch):
    """Incomplete dependency arrays are unsafe, so the original exception remains visible."""
    handler = _install_logger(monkeypatch, lineiterator_module, logging.DEBUG)

    class FailingAction(linebuffer_module.LineActions):
        def once(self, start, end):
            raise RuntimeError("synthetic-secret")

    action = FailingAction()
    indicator = SimpleNamespace(data=action, datas=[], _clock=None)
    with pytest.raises(RuntimeError, match="synthetic-secret"):
        lineiterator_module._ensure_lineactions_inputs_computed(indicator, 1)

    class FailingOnce:
        def forward(self):
            raise RuntimeError("synthetic-secret")

        def next(self):
            raise AssertionError("next must not run after forward failure")

    with pytest.raises(RuntimeError, match="synthetic-secret"):
        lineiterator_module.LineIterator.once(FailingOnce(), 0, 1)

    assert handler.records == []


def test_lineiterator_orphan_once_capability_guard_keeps_linebuffers_silent(monkeypatch):
    """A direct LineBuffer is not an orphan LineIterator and has no ``_once`` hook."""
    handler = _install_logger(monkeypatch, lineiterator_module, logging.DEBUG)
    line = linebuffer_module.LineBuffer()
    indicator = SimpleNamespace(data=line, datas=[], _clock=None)

    assert not hasattr(line, "_once")
    lineiterator_module._ensure_lineactions_inputs_computed(indicator, 1)

    class NonCallableOnce:
        array = []
        _once = None

        def once(self, start, end):
            raise AssertionError("a non-callable _once must not schedule once")

    lineiterator_module._ensure_lineactions_inputs_computed(
        SimpleNamespace(data=NonCallableOnce(), datas=[], _clock=None), 1
    )

    class FailingOrphan:
        array = []

        def once(self, start, end):
            raise AssertionError("orphan scheduling must use _once")

        def _once(self, start, end):
            raise RuntimeError("synthetic-secret")

    with pytest.raises(RuntimeError, match="synthetic-secret"):
        lineiterator_module._ensure_lineactions_inputs_computed(
            SimpleNamespace(data=FailingOrphan(), datas=[], _clock=None), 1
        )

    assert handler.records == []


def test_strategybase_compatibility_constructor_propagates_user_error_without_logs(monkeypatch):
    """The legacy StrategyBase path never turns a user constructor failure into a run."""

    handler = _install_logger(monkeypatch, lineiterator_module, logging.DEBUG)

    class RaisingCompatibilityStrategy(lineiterator_module.StrategyBase):
        def __init__(self):
            raise RuntimeError("synthetic-secret")

    instance = object.__new__(RaisingCompatibilityStrategy)
    with pytest.raises(RuntimeError, match="synthetic-secret"):
        lineiterator_module.StrategyBase.__init__(instance)

    assert handler.records == []


@pytest.mark.parametrize(
    ("path", "key", "message"),
    [
        (
            "indicator_alias",
            "lineiterator.indicator_alias.tema_import_recovery",
            "TEMA indicator alias import failed; skipping alias registration",
        ),
        (
            "strategy_patch",
            "lineroot.strategy_patch.import_recovery",
            "Strategy compatibility patch deferred because Strategy is not importable",
        ),
    ],
)
@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
def test_import_compatibility_recovery_warnings_are_bounded_and_redacted(
    monkeypatch, level, path, key, message
):
    """Unavailable optional imports preserve startup compatibility without log storms."""
    module = lineiterator_module if path == "indicator_alias" else lineroot_module
    handler = _install_logger(monkeypatch, module, level)
    original_import = builtins.__import__

    def unavailable_import(name, globals=None, locals=None, fromlist=(), level=0):
        is_tema_alias = (
            path == "indicator_alias"
            and name == "backtrader.indicators.tema"
            and "TripleExponentialMovingAverage" in fromlist
            and level == 0
        )
        is_strategy_patch = (
            path == "strategy_patch"
            and name == "strategy"
            and "Strategy" in fromlist
            and level == 1
        )
        if is_tema_alias or is_strategy_patch:
            raise ImportError("synthetic-secret")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", unavailable_import)
    for _ in range(250):
        if path == "indicator_alias":
            lineiterator_module.IndicatorBase._register_indicator_aliases()
        else:
            lineroot_module._apply_strategy_patch()

    # ``sma.py`` currently has its own optional import compatibility path, so
    # a complete alias registration exercises both that path and the targeted
    # TEMA failure. Each retained startup fallback must remain independently
    # bounded.
    expected_keys = {key}
    if path == "indicator_alias":
        expected_keys.add("lineiterator.indicator_alias.sma_import_recovery")

    assert len(handler.records) == len(expected_keys) * 3
    rendered = _assert_safe_records(handler.records)
    assert message in "\n".join(rendered)
    for expected_key in expected_keys:
        assert expected_key in "\n".join(rendered)
        states = [
            state
            for (
                _name,
                state_key,
                _level,
                _exception_type,
            ), state in log_message._throttle_state.items()
            if state_key == expected_key
        ]
        assert len(states) == 1
        assert states[0]["total"] == 250
        assert states[0]["count"] == 49

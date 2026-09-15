"""Regression coverage for LineBuffer recovery diagnostics.

Expected protocol probes stay silent.  Branches that keep running after a
broken dependency emit one static, throttled diagnostic only after logging is
explicitly configured; branches without a safe value preserve their exception.
"""

import logging
import math
from contextlib import contextmanager

import pandas as pd
import pytest

import backtrader as bt
import backtrader.linebuffer as linebuffer_module
from backtrader.utils import log_message

SECRET = "synthetic-secret"


class _BrokenClassNameMeta(type):
    """Make only the indicator-classification name lookup fail."""

    def __getattribute__(cls, name):
        if name == "__name__":
            raise RuntimeError(SECRET)
        return super().__getattribute__(name)


class _BrokenIndicatorClassificationLine(
    linebuffer_module.LineBuffer, metaclass=_BrokenClassNameMeta
):
    # The datetime classification uses this stable name instead of the class name.
    _name = "plain"


class _BrokenDatetimeClassificationLine(linebuffer_module.LineBuffer):
    @property
    def _name(self):
        raise RuntimeError(SECRET)


class RecordingHandler(logging.Handler):
    """In-memory sink that does not alter the process root logger."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture(autouse=True)
def clean_logging_state():
    """Keep logger handlers and throttling state isolated between cases."""
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)
    yield
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)


@contextmanager
def capture_linebuffer_logging(level):
    """Configure only the library namespace and restore it after capture."""
    bt.configure_logging(level=level, console=False, backend="stdlib")
    module_logger = linebuffer_module.logger
    previous_level = module_logger.level
    handler = RecordingHandler()
    module_logger.setLevel(logging.NOTSET)
    module_logger.addHandler(handler)
    try:
        yield handler
    finally:
        module_logger.removeHandler(handler)
        module_logger.setLevel(previous_level)
        log_message.reset_logging()


def _formatted_records(handler):
    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    return [formatter.format(record) for record in handler.records]


def assert_safe_records(handler):
    """Format every record, including any traceback field, before checking it."""
    rendered = _formatted_records(handler)
    text = "\n".join(rendered)
    assert SECRET not in text
    assert "Traceback" not in text
    assert all(not record.exc_info for record in handler.records)
    return rendered


def assert_bounded_recovery_records(handler, key, expected_total=250, level=logging.WARNING):
    """The first event plus the 100/200-event summaries bound 250 failures."""
    assert len(handler.records) == 3
    assert all(record.levelno == level for record in handler.records)
    rendered = assert_safe_records(handler)
    assert key in "\n".join(rendered)

    matching_states = [
        state
        for (
            _logger_name,
            state_key,
            _level,
            _exception_type,
        ), state in log_message._throttle_state.items()
        if state_key == key
    ]
    assert len(matching_states) == 1
    assert matching_states[0]["count"] == 49
    assert matching_states[0]["total"] == expected_total


def assert_pristine_logging(handler):
    """Ensure the test's opt-in capture did not leave a library configuration."""
    root = logging.getLogger(log_message.ROOT_LOGGER_NAME)
    assert handler not in linebuffer_module.logger.handlers
    assert root.level == logging.NOTSET
    assert root.propagate is False
    assert any(isinstance(item, logging.NullHandler) for item in root.handlers)
    assert not any(getattr(item, "_backtrader_managed", False) for item in root.handlers)


@pytest.mark.parametrize(
    ("classification", "key"),
    [
        (
            "indicator",
            "linebuffer.init.indicator_classification_recovery",
        ),
        (
            "datetime",
            "linebuffer.init.datetime_classification_recovery",
        ),
    ],
)
@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_linebuffer_init_classification_recovery_is_bounded_and_redacted(
    level, classification, key
):
    """Broken line metadata retains default classification without leaking the failure."""
    line_type = {
        "indicator": _BrokenIndicatorClassificationLine,
        "datetime": _BrokenDatetimeClassificationLine,
    }[classification]

    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            line = line_type()
            assert line._is_indicator is False
            assert line._is_datetime_line is False
            assert line._default_value == 0.0

        assert_bounded_recovery_records(handler, key)

    assert_pristine_logging(handler)


@pytest.mark.parametrize(
    ("classification", "key"),
    [
        (
            "indicator",
            "linebuffer.refresh.indicator_classification_recovery",
        ),
        (
            "datetime",
            "linebuffer.refresh.datetime_classification_recovery",
        ),
    ],
)
@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_linebuffer_refresh_classification_recovery_is_bounded_and_redacted(
    level, classification, key
):
    """Refreshing attached lines keeps the same safe classification fallback."""
    line_type = {
        "indicator": _BrokenIndicatorClassificationLine,
        "datetime": _BrokenDatetimeClassificationLine,
    }[classification]

    # Construction runs before logging is configured, so this test captures
    # only the refresh recovery that it is intended to exercise.
    line = line_type()
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            line._refresh_cached_line_flags()
            assert line._is_indicator is False
            assert line._is_datetime_line is False
            assert line._default_value == 0.0

        assert_bounded_recovery_records(handler, key)

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_expected_linebuffer_index_and_end_of_data_probes_stay_silent(level):
    """Empty indexing and normal out-of-data IndexError are not diagnostics."""

    class EndOfDataLine(linebuffer_module.LineBuffer):
        def datetime(self, ago=0, tz=None, naive=True):
            raise IndexError(SECRET)

    with capture_linebuffer_logging(level) as handler:
        buffer = linebuffer_module.LineBuffer()
        end_of_data = EndOfDataLine()
        for _ in range(250):
            assert buffer[0] == 0.0
            with pytest.raises(IndexError, match=SECRET):
                end_of_data.date()

        assert handler.records == []

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_broken_clock_forces_forward_with_bounded_warning(level):
    """A bad clock keeps the one-step recovery without disclosing its payload."""

    class BrokenClock:
        def __len__(self):
            raise RuntimeError(SECRET)

    class Action:
        _once_called = False
        _clock = BrokenClock()
        _minperiod = 2

        def __init__(self):
            self.forward_count = 0
            self.prenext_count = 0

        def __len__(self):
            return 0

        def forward(self):
            self.forward_count += 1

        def prenext(self):
            self.prenext_count += 1

        def nextstart(self):
            raise AssertionError("must remain below minperiod")

        def next(self):
            raise AssertionError("must remain below minperiod")

    action = Action()
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            linebuffer_module.LineActions._next_old(action)

        assert action.forward_count == 250
        assert action.prenext_count == 250
        assert_bounded_recovery_records(handler, "linebuffer.lineactions.next_old.clock_failure")

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_linebuffer_forward_clock_recovery_is_bounded(level):
    """A broken optional clock must not block storage advancement."""

    class BrokenClock:
        def __len__(self):
            raise RuntimeError(SECRET)

    buffer = linebuffer_module.LineBuffer()
    buffer._clock = BrokenClock()
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            buffer.forward()

        assert buffer.lencount == 250
        assert len(buffer.array) == 250
        assert_bounded_recovery_records(handler, "linebuffer.forward.clock_length_recovery")

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_binary_next_recovery_keeps_nan_with_bounded_warning(level):
    """A failing binary operation preserves the NaN fallback on every call."""
    left = linebuffer_module.LineBuffer()
    right = linebuffer_module.LineBuffer()
    left.forward()
    left[0] = 1.0
    right.forward()
    right[0] = 2.0

    def broken_operation(_left, _right):
        raise RuntimeError(SECRET)

    operation = linebuffer_module.LinesOperation(left, right, broken_operation)
    operation.forward()
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            operation.next()

        assert math.isnan(operation.array[operation._idx])
        assert_bounded_recovery_records(handler, "linebuffer.lines_operation.next.nan_recovery")

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_binary_once_recovery_keeps_nan_without_fast_path_duplicates(level):
    """The batch fallback reports element recovery, without DEBUG traceback noise."""
    left = linebuffer_module.LineBuffer()
    right = linebuffer_module.LineBuffer()
    for value in range(250):
        left.forward()
        left[0] = float(value)
        right.forward()
        right[0] = float(value)

    def broken_operation(_left, _right):
        raise RuntimeError(SECRET)

    operation = linebuffer_module.LinesOperation(left, right, broken_operation)
    with capture_linebuffer_logging(level) as handler:
        operation.once(0, 250)

        assert len(operation.array) >= 250
        assert all(math.isnan(value) for value in operation.array[:250])
        assert_bounded_recovery_records(handler, "linebuffer.lines_operation.once.nan_recovery")

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_unary_once_recovery_keeps_zeroes_with_bounded_warning(level):
    """A failed unary batch uses 0.0 for each sample without 250 warning records."""
    source = linebuffer_module.LineBuffer()
    for value in range(250):
        source.forward()
        source[0] = float(value)

    def broken_operation(_value):
        raise RuntimeError(SECRET)

    operation = linebuffer_module.LineOwnOperation(source, broken_operation)
    with capture_linebuffer_logging(level) as handler:
        operation.once(0, 250)

        assert list(operation.array) == [0.0] * 250
        assert_bounded_recovery_records(handler, "linebuffer.line_own_operation.once.zero_recovery")

    assert_pristine_logging(handler)


@pytest.mark.parametrize(
    ("failure_kind", "key"),
    [
        ("child", "linebuffer.lineactions.once.child_failure"),
        ("argument", "linebuffer.lineactions.once.argument_failure"),
        ("condition", "linebuffer.lineactions.once.condition_failure"),
    ],
)
@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_lineactions_once_propagates_required_dependency_failures(level, failure_kind, key):
    """A failed dependency must not permit a parent batch result to be fabricated."""

    class BrokenInput:
        array = []

        def once(self, start, end):
            raise RuntimeError(SECRET)

    class BrokenChild:
        def _once(self, start, end):
            raise RuntimeError(SECRET)

    class Action:
        _lineiterators = {0: [BrokenChild()]} if failure_kind == "child" else {}
        args = [BrokenInput()] if failure_kind == "argument" else []
        cond = BrokenInput() if failure_kind == "condition" else None

        def preonce(self, start, end):
            return None

        def once(self, start, end):
            self.calls += 1

        def oncebinding(self):
            return None

        def __init__(self):
            self.calls = 0

    action = Action()
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            with pytest.raises(RuntimeError, match=SECRET):
                linebuffer_module.LineActions._once(action, 0, 1)

        assert action.calls == 0
        assert_bounded_recovery_records(handler, key, level=logging.ERROR)

    assert_pristine_logging(handler)


@pytest.mark.parametrize("hook, key", [("preonce", "preonce_failure"), ("once", "main_failure")])
@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_lineactions_once_propagates_unsafe_hook_errors_with_safe_logs(level, hook, key):
    """No fabricated batch output is allowed after a user hook fails."""

    class Action:
        _lineiterators = {}

        def preonce(self, start, end):
            if hook == "preonce":
                raise RuntimeError(SECRET)

        def once(self, start, end):
            if hook == "once":
                raise RuntimeError(SECRET)

        def oncebinding(self):
            return None

    action = Action()
    full_key = f"linebuffer.lineactions.once.{key}"
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            with pytest.raises(RuntimeError, match=SECRET):
                linebuffer_module.LineActions._once(action, 0, 1)

        assert_bounded_recovery_records(handler, full_key, level=logging.ERROR)

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_reset_recovery_is_bounded_and_resets_normally(level):
    """A malformed owner cannot leak an exception or preserve a stale runonce array."""

    class BrokenOwner:
        @property
        def _owner(self):
            raise RuntimeError(SECRET)

    buffer = linebuffer_module.LineBuffer()
    buffer._owner = BrokenOwner()
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            buffer.reset()

        assert buffer.lencount == 0
        assert buffer.idx == -1
        assert len(buffer.array) == 0
        assert_bounded_recovery_records(handler, "linebuffer.reset.runonce_preservation_recovery")

    assert_pristine_logging(handler)


def _shift_values(values):
    source = linebuffer_module.LineBuffer()
    shifted = linebuffer_module._LineForward(source, 1)
    for value in values:
        source.forward()
        source[0] = value
        shifted.forward()
        shifted.next()
    return list(shifted.array)


def _assert_forward_values(values):
    assert values[:2] == [20.0, 30.0]
    assert math.isnan(values[2])


def test_lineforward_preserves_offset_minperiod_and_cerebro_mode_parity():
    """Positive ago is a future shift in direct, runnext, and runonce execution."""
    _assert_forward_values(_shift_values([10.0, 20.0, 30.0]))

    source = linebuffer_module.LineBuffer()
    for value in (10.0, 20.0, 30.0):
        source.forward()
        source[0] = value
    direct_once = linebuffer_module._LineForward(source, 1)
    direct_once.once(0, 3)
    _assert_forward_values(list(direct_once.array))

    for source_period, ago, expected_period in ((5, 3, 5), (10, 12, 12)):
        period_source = linebuffer_module.LineBuffer()
        period_source._minperiod = source_period
        assert linebuffer_module._LineForward(period_source, ago)._minperiod == expected_period

    frame = pd.DataFrame(
        {
            "open": [10.0, 20.0, 30.0],
            "high": [10.0, 20.0, 30.0],
            "low": [10.0, 20.0, 30.0],
            "close": [10.0, 20.0, 30.0],
            "volume": [1.0, 1.0, 1.0],
        },
        index=pd.date_range("2020-01-01", periods=3),
    )

    class ForwardIndicator(bt.Indicator):
        lines = ("out",)

        def __init__(self):
            self.shift = self.data.close(1)
            self.lines.out = self.shift

    class CaptureStrategy(bt.Strategy):
        def __init__(self):
            self.forward_indicator = ForwardIndicator(self.data)

    mode_values = []
    for runonce in (False, True):
        cerebro = bt.Cerebro(runonce=runonce)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(CaptureStrategy)
        strategy = cerebro.run()[0]
        values = list(strategy.forward_indicator.out.array)
        _assert_forward_values(values)
        mode_values.append(values[:3])

    assert mode_values[0][:2] == mode_values[1][:2] == [20.0, 30.0]
    assert math.isnan(mode_values[0][2])
    assert math.isnan(mode_values[1][2])


def test_linebuffer_recovery_is_silent_without_logging_configuration(capsys):
    """The warning helper remains inert until callers opt in to logging."""
    left = linebuffer_module.LineBuffer()
    right = linebuffer_module.LineBuffer()
    left.forward()
    left[0] = 1.0
    right.forward()
    right[0] = 2.0

    def broken_operation(_left, _right):
        raise RuntimeError(SECRET)

    operation = linebuffer_module.LinesOperation(left, right, broken_operation)
    operation.forward()
    operation.next()

    assert math.isnan(operation.array[operation._idx])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert log_message._throttle_state == {}


class _BatchActionProbe:
    _lineiterators = {}

    def preonce(self, start, end):
        return None

    def once(self, start, end):
        return None

    def oncebinding(self):
        return None


@pytest.mark.parametrize(
    ("attribute", "key"),
    [
        ("clock", "linebuffer.lineactions.once.clock_length_recovery"),
        ("data", "linebuffer.lineactions.once.data_length_recovery"),
        ("length", "linebuffer.lineactions.once.length_recovery"),
    ],
)
@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_lineactions_once_length_recoveries_are_bounded_and_safe(level, attribute, key):
    """All retained batch-length fallbacks keep the requested range safely."""

    class AlternatingClock:
        def __init__(self):
            self.calls = 0

        def __bool__(self):
            return True

        def buflen(self):
            self.calls += 1
            if self.calls % 2 == 0:
                raise RuntimeError(SECRET)
            return 1

        def __len__(self):
            return 1

    class BrokenData:
        def buflen(self):
            raise RuntimeError(SECRET)

        def __len__(self):
            return 1

    class BrokenComparable:
        def __gt__(self, other):
            raise RuntimeError(SECRET)

    class LengthData:
        def buflen(self):
            return BrokenComparable()

    action = _BatchActionProbe()
    if attribute == "clock":
        action._clock = AlternatingClock()
    elif attribute == "data":
        action.datas = [BrokenData()]
    else:
        action.datas = [LengthData()]

    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            linebuffer_module.LineActions._once(action, 0, 1)

        assert_bounded_recovery_records(handler, key)

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_lineactions_once_clock_preflight_failure_is_logged_before_propagating(level):
    """A required preflight clock error propagates after one safe ERROR diagnostic."""

    class BrokenClock:
        def __bool__(self):
            return True

        def buflen(self):
            raise RuntimeError(SECRET)

    action = _BatchActionProbe()
    action._clock = BrokenClock()

    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            with pytest.raises(RuntimeError, match=SECRET):
                linebuffer_module.LineActions._once(action, 0, 1)

        assert_bounded_recovery_records(
            handler,
            "linebuffer.lineactions.once.clock_preflight_failure",
            level=logging.ERROR,
        )

    assert_pristine_logging(handler)


@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_lineactions_dnames_recovery_is_bounded_and_redacted(level):
    """Broken data names retain the empty-name fallback without exposing payloads."""

    class BrokenData:
        lines = []

        @property
        def _name(self):
            raise RuntimeError(SECRET)

    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            action = linebuffer_module.LineActions.__new__(
                linebuffer_module.LineActions, BrokenData()
            )
            assert action.dnames == {}

        assert_bounded_recovery_records(handler, "linebuffer.lineactions.dnames_recovery")

    assert_pristine_logging(handler)


@pytest.mark.parametrize(
    ("operation_factory", "key", "expected_values"),
    [
        (
            lambda source: linebuffer_module.LinesOperation(
                source,
                source,
                lambda left, right: left + right,
                parent_a=_BrokenParentOnce(),
            ),
            "linebuffer.lines_operation.once.parent_recovery",
            [0.0, 2.0, 4.0],
        ),
        (
            lambda source: _make_broken_operand_operation(source),
            "linebuffer.lines_operation.once.operand_recovery",
            [0.0, 2.0, 4.0],
        ),
        (
            lambda source: linebuffer_module.LineOwnOperation(
                source,
                lambda value: value,
                parent_a=_BrokenParentOnce(),
            ),
            "linebuffer.line_own_operation.once.parent_recovery",
            [0.0, 1.0, 2.0],
        ),
    ],
)
@pytest.mark.parametrize("level", ("DEBUG", "INFO"))
def test_batch_parent_and_operand_recoveries_are_bounded(
    level, operation_factory, key, expected_values
):
    """Nested batch failures retain the existing computation and emit one key."""

    source = linebuffer_module.LineBuffer()
    for value in range(250):
        source.forward()
        source[0] = float(value)

    operation = operation_factory(source)
    with capture_linebuffer_logging(level) as handler:
        for _ in range(250):
            operation.once(0, 250)

        assert list(operation.array[:3]) == expected_values
        assert_bounded_recovery_records(handler, key)

    assert_pristine_logging(handler)


class _BrokenParentOnce:
    def _once(self, start, end):
        raise RuntimeError(SECRET)

    def once(self, start, end):
        raise RuntimeError(SECRET)


class _BrokenOperandOnce(linebuffer_module.LineActions):
    def __init__(self, values):
        super().__init__()
        self.array.extend(values)

    def once(self, start, end):
        raise RuntimeError(SECRET)


def _make_broken_operand_operation(source):
    operation = linebuffer_module.LinesOperation(
        _BrokenOperandOnce(source.array),
        source,
        lambda left, right: left + right,
    )
    # The operand itself is sufficient to exercise the operand recovery.
    # Avoid the intentionally separate parent recovery path in this case.
    operation._parent_a = None
    return operation

"""Safe logging for strategies skipped during construction."""

import logging

import backtrader as bt
import pytest
from backtrader._cerebro.execution import _safe_strategy_identity


_PRIVATE_SKIP_SENTINEL = "skip-private-payload-7f3a9c"


class _SkipWithPrivateReason(bt.Strategy):
    def __init__(self):
        raise bt.errors.StrategySkipError(_PRIVATE_SKIP_SENTINEL)

    def next(self):
        pass


class _SurvivingStrategy(bt.Strategy):
    def next(self):
        pass


def test_real_strategy_skip_logs_identity_and_finite_reason_only(cerebro_with_data, bt_caplog):
    bt_caplog.set_level(logging.WARNING, logger="backtrader.cerebro")
    cerebro_with_data.addstrategy(_SkipWithPrivateReason)
    cerebro_with_data.addstrategy(_SurvivingStrategy)

    results = cerebro_with_data.run()

    assert len(results) == 1
    assert type(results[0]) is _SurvivingStrategy
    skip_records = [
        record
        for record in bt_caplog.records
        if record.name == "backtrader.cerebro" and "strategy skipped" in record.getMessage()
    ]
    assert len(skip_records) == 1
    message = skip_records[0].getMessage()
    assert "strategy=" in message
    assert message.endswith("._SkipWithPrivateReason reason=StrategySkipError")
    assert _PRIVATE_SKIP_SENTINEL not in message


@pytest.mark.parametrize(
    "class_name",
    (
        "Strategy\r\nInjectedLine",
        "Strategy\x01\x1f\x7fControl",
        "Strategy" + ("x" * 400),
    ),
    ids=("crlf", "control-characters", "oversized"),
)
def test_strategy_identity_sanitizes_and_bounds_untrusted_class_names(class_name):
    strategy_class = type("InitialName", (), {})
    strategy_class.__name__ = class_name
    strategy_class.__qualname__ = class_name
    strategy_class.__module__ = "tests.strategy_identity"

    identity = _safe_strategy_identity(strategy_class)

    assert len(identity) <= 160
    assert not any(ord(character) < 32 or ord(character) == 127 for character in identity)
    assert "\r" not in identity
    assert "\n" not in identity
    if len(class_name) > 160:
        assert len(identity) == 160


def test_strategy_identity_does_not_call_metaclass_formatting_hooks():
    formatter_sentinel = "metaclass-private-format-sentinel"
    calls = []

    class FormattingMeta(type):
        def __getattribute__(cls, name):
            if name in {"__module__", "__name__", "__qualname__"}:
                calls.append("getattribute:" + name)
                raise AssertionError(formatter_sentinel)
            return super().__getattribute__(name)

        def __repr__(cls):
            calls.append("repr")
            return formatter_sentinel

        def __str__(cls):
            calls.append("str")
            return formatter_sentinel

    class FormattingStrategy(metaclass=FormattingMeta):
        pass

    identity = _safe_strategy_identity(FormattingStrategy)
    rendered = "strategy={}".format(identity)

    assert calls == []
    assert len(identity) <= 160
    assert identity.endswith(".FormattingStrategy")
    assert formatter_sentinel not in identity
    assert formatter_sentinel not in rendered

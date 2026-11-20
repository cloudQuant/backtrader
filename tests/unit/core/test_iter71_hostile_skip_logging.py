"""Hostile class metadata must not interrupt StrategySkipError handling."""

import logging

import backtrader as bt
import pytest
from backtrader._cerebro.execution import _safe_strategy_identity


_DESCRIPTOR_SENTINEL = "hostile-module-descriptor-private-91d73c"
_SKIP_SENTINEL = "hostile-strategy-skip-private-34c6ab"


class _ArmedModuleDescriptor:
    """A metaclass data descriptor that fails only after registration."""

    def __init__(self, module_name):
        self.module_name = module_name
        self.error = None
        self.reads = 0

    def __get__(self, instance, owner):
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.module_name

    def __set__(self, instance, value):
        # Making this a data descriptor is necessary for type.__getattribute__
        # to consult it ahead of the strategy class's own __module__ string.
        self.value = value


def _make_hostile_skipping_strategy():
    module_descriptor = _ArmedModuleDescriptor(__name__)

    class HostileMeta(type(bt.Strategy)):
        __module__ = module_descriptor

    class HostileSkipStrategy(bt.Strategy, metaclass=HostileMeta):
        def __init__(self):
            raise bt.errors.StrategySkipError(_SKIP_SENTINEL)

    return HostileSkipStrategy, module_descriptor


class _SurvivingStrategy(bt.Strategy):
    def next(self):
        pass


@pytest.mark.parametrize("channel", (False, True), ids=("ordinary", "channel"))
def test_real_cerebro_skip_paths_survive_hostile_module_descriptor(
    channel, cerebro_with_data, bt_caplog
):
    bt_caplog.set_level(logging.WARNING, logger="backtrader.cerebro")
    hostile_strategy, module_descriptor = _make_hostile_skipping_strategy()
    cerebro_with_data.addstrategy(hostile_strategy)
    cerebro_with_data.addstrategy(_SurvivingStrategy)

    # Arm only after class creation and addstrategy have completed so the
    # descriptor fault occurs at the diagnostic identity read in the skip path.
    module_descriptor.error = RuntimeError(_DESCRIPTOR_SENTINEL)
    results = cerebro_with_data.run(channel=True if channel else None)

    assert len(results) == 1
    assert type(results[0]) is _SurvivingStrategy
    assert module_descriptor.reads >= 1

    skip_marker = (
        "channel strategy skipped during construction"
        if channel
        else "strategy skipped during construction"
    )
    records = [
        record
        for record in bt_caplog.records
        if record.name == "backtrader.cerebro" and skip_marker in record.getMessage()
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.endswith("strategy=unknown reason=StrategySkipError")
    assert _DESCRIPTOR_SENTINEL not in message
    assert _SKIP_SENTINEL not in message


def test_strategy_identity_does_not_catch_base_exception_from_descriptor():
    strategy_class, module_descriptor = _make_hostile_skipping_strategy()
    module_descriptor.error = KeyboardInterrupt(_DESCRIPTOR_SENTINEL)

    with pytest.raises(KeyboardInterrupt, match=_DESCRIPTOR_SENTINEL):
        _safe_strategy_identity(strategy_class)

    assert module_descriptor.reads >= 1

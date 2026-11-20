"""Channel-mode StrategySkipError logging must be useful and payload-safe."""

import logging

import backtrader as bt


_PRIVATE_SKIP_SENTINEL = "channel-skip-private-payload-4b8e21"


class _SkipWithPrivateReason(bt.Strategy):
    def __init__(self):
        raise bt.errors.StrategySkipError(_PRIVATE_SKIP_SENTINEL)


class _SurvivingStrategy(bt.Strategy):
    pass


def test_channel_strategy_skip_logs_bounded_identity_without_exception_message(bt_caplog):
    bt_caplog.set_level(logging.WARNING, logger="backtrader.cerebro")
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(_SkipWithPrivateReason)
    cerebro.addstrategy(_SurvivingStrategy)

    results = cerebro.run(channel=[])

    assert len(results) == 1
    assert type(results[0]) is _SurvivingStrategy
    records = [
        record
        for record in bt_caplog.records
        if record.name == "backtrader.cerebro"
        and "channel strategy skipped during construction" in record.getMessage()
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "strategy=" in message
    assert message.endswith("._SkipWithPrivateReason reason=StrategySkipError")
    assert _PRIVATE_SKIP_SENTINEL not in message

"""Gateway-only strategy intent and cash sizer behavior."""
from types import SimpleNamespace

import pytest

import backtrader as bt
from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework


@pytest.fixture
def gateway_strategy(monkeypatch):
    data, broker, strategy = framework()
    broker.store = SimpleNamespace(_gateway_mode=True, gateway_sequence=None,
        gateway_strategy_config=SimpleNamespace(
            instruments_by_ref={'rb': SimpleNamespace(native_symbol='rb')},
            strategy_finance_currency='CNY'))
    position = [3.0]
    monkeypatch.setattr(broker, 'getposition', lambda _data, **_kw: bt.Position(5, 1))
    monkeypatch.setattr(broker, 'get_strategy_position', lambda _strategy, _data, **_kw:
                        bt.Position(position[0], 1))
    calls = []
    monkeypatch.setattr(strategy, 'buy', lambda **kw: calls.append(('buy', kw)) or kw)
    monkeypatch.setattr(strategy, 'sell', lambda **kw: calls.append(('sell', kw)) or kw)
    return data, broker, strategy, position, calls


def test_gateway_close_preserves_close_intent_and_rejects_conflict(gateway_strategy):
    _, _, strategy, position, calls = gateway_strategy
    strategy.close(offset='close_today')
    assert calls[-1][0] == 'sell' and calls[-1][1]['offset'] == 'close_today'
    position[0] = -2
    strategy.close()
    assert calls[-1][0] == 'buy' and calls[-1][1]['offset'] == 'close'
    with pytest.raises(ValueError, match='offset conflicts'):
        strategy.close(offset='open')


@pytest.mark.parametrize('current,target,side,offset', [
    (3, 2, 'sell', 'close'), (3, 4, 'buy', 'open'),
    (-3, -2, 'buy', 'close'), (-3, -4, 'sell', 'open'), (0, -1, 'sell', 'open'),
])
def test_gateway_target_size_has_explicit_intent(gateway_strategy, current, target, side, offset):
    _, _, strategy, position, calls = gateway_strategy
    position[0] = current
    strategy.order_target_size(target=target)
    assert calls[-1][0] == side and calls[-1][1]['offset'] == offset


def test_gateway_target_crossing_zero_and_unknown_valuation_are_rejected(gateway_strategy):
    _, _, strategy, _, calls = gateway_strategy
    with pytest.raises(ValueError, match='cross zero'):
        strategy.order_target_size(target=-1)
    with pytest.raises(ValueError, match='offset conflicts'):
        strategy.order_target_size(target=2, offset='open')
    with pytest.raises(ValueError, match='valuation is unavailable'):
        strategy.order_target_value(target=10)
    with pytest.raises(ValueError, match='valuation is unavailable'):
        strategy.order_target_percent(target=.5)
    assert calls == []
    strategy.order_target_percent(target=0)
    assert calls[-1][1]['offset'] == 'close'


def test_gateway_sizer_guards_cash_but_not_cash_independent_sizer(gateway_strategy):
    data, broker, strategy, _, _ = gateway_strategy
    broker.getcash = lambda: float('nan')
    called = []
    class CashSizer(bt.Sizer):
        def _getsizing(self, *_args):
            called.append('cash')
            return 1
    class FixedSizer(CashSizer):
        uses_account_cash = False
    cash = CashSizer()
    cash.set(strategy, broker)
    with pytest.raises(ValueError, match='cash is unavailable'):
        cash.getsizing(data, True)
    assert not called
    fixed = FixedSizer()
    fixed.set(strategy, broker)
    assert fixed.getsizing(data, True) == 1 and called == ['cash']


def test_gateway_position_getters_require_strategy_view_and_reject_account_alias(gateway_strategy):
    data, broker, strategy, _, _ = gateway_strategy
    assert strategy.getposition(data).size == 5
    assert strategy.get_strategy_position(data).size == 3
    assert strategy.getaccountposition(data).size == 5
    strategy.account_book = object()
    with pytest.raises(ValueError, match='cannot mix'):
        strategy.get_strategy_position(data)


def test_gateway_dual_side_close_passes_the_selected_leg(gateway_strategy, monkeypatch):
    _, broker, strategy, _, calls = gateway_strategy
    monkeypatch.setattr(broker, 'get_param', lambda *_args, **_kw: 'dual_side')
    monkeypatch.setattr(broker, 'get_strategy_position', lambda _strategy, _data, side=None, **_kw:
                        bt.Position(3 if side == 'long' else 0, 1))
    strategy.close(position_side='long')
    assert calls[-1][0] == 'sell'
    assert calls[-1][1]['offset'] == 'close' and calls[-1][1]['position_side'] == 'long'


def test_gateway_builtin_sizers_never_use_account_position(gateway_strategy):
    from backtrader.sizers.fixedsize import FixedReverser, FixedSizeTarget
    from backtrader.sizers.percents_sizer import PercentSizer
    data, broker, strategy, position, _ = gateway_strategy
    position[0] = 0  # Account fixture holds 5, but this strategy owns none.
    reverser = FixedReverser(stake=2)
    reverser.set(strategy, broker)
    assert reverser._getsizing(None, 100, data, True) == 2
    pct = PercentSizer(percents=20)
    pct.set(strategy, broker)
    assert pct._getsizing(None, 100, data, True) == 2
    target = FixedSizeTarget(stake=10, tranches=2)
    target.set(strategy, broker)
    assert target._getsizing(None, 100, data, True) == 5
    position[0] = 2
    assert target._getsizing(None, 100, data, True) == 7
    target.setsizing(10)
    assert target.get_param('stake') == 7


def test_gateway_builtin_sizer_rejects_unknown_strategy_position(gateway_strategy, monkeypatch):
    from backtrader.sizers.fixedsize import FixedReverser
    data, broker, strategy, _, _ = gateway_strategy
    monkeypatch.setattr(broker, 'get_strategy_position', lambda *_a, **_kw:
                        (_ for _ in ()).throw(RuntimeError('STRATEGY_POSITION_UNAVAILABLE')))
    sizer = FixedReverser()
    sizer.set(strategy, broker)
    with pytest.raises(RuntimeError, match='STRATEGY_POSITION_UNAVAILABLE'):
        sizer._getsizing(None, 100, data, True)


def test_gateway_strategy_account_book_sizer_rejects_mixed_book(gateway_strategy):
    from backtrader.sizers.strategy_account_book import StrategyAccountBookPercentSizer
    data, broker, strategy, _, _ = gateway_strategy
    strategy.account_book = object()
    sizer = StrategyAccountBookPercentSizer()
    sizer.set(strategy, broker)
    with pytest.raises(ValueError, match='cannot mix'):
        sizer.getsizing(data, True)


def test_single_strategy_backtest_has_explicit_strategy_views():
    import pandas as pd
    seen = []
    class OnlyStrategy(bt.Strategy):
        def next(self):
            seen.append((self.get_strategy_cash(), self.get_strategy_value(),
                         self.get_strategy_position().size))
    frame = pd.DataFrame({'open': [10], 'high': [10], 'low': [10], 'close': [10],
                          'volume': [1]}, index=pd.to_datetime(['2026-01-01']))
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(OnlyStrategy)
    cerebro.run()
    assert seen == [(10000.0, 10000.0, 0)]


def test_gateway_auto_bind_reports_missing_configuration(gateway_strategy):
    _, broker, strategy, _, _ = gateway_strategy
    del broker.store.gateway_strategy_config
    with pytest.raises(RuntimeError, match='CONFIG_UNAVAILABLE'):
        broker._gateway_auto_bind(strategy)

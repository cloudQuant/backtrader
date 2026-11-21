"""Compare current and HEAD TriggerLine against the same public strategy fixture."""
import ast
import datetime
import json
import math
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backtrader as bt
import backtrader.indicators.contrib.trigger_line as trigger
from tests.functional.strategies.trend_following import test_0245_0808_trigger_line as fixture


def baseline_next():
    source = subprocess.check_output(
        ['git', 'show', 'HEAD:backtrader/indicators/contrib/trigger_line.py'],
        text=True, encoding='utf-8',
    )
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TriggerLine')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'next')
    ns = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<head-trigger-next>', 'exec'), ns)
    return ns['next']


def run(data, signal_data, method):
    trigger.TriggerLine.next = method

    class Instrumented(fixture.ExpTriggerLineStrategy):
        def __init__(self):
            super().__init__()
            self.events = []
            self.comparisons = []
            self.rows = []

        def _point(self):
            return {'bar': len(self.base), 'time': self.base.datetime.datetime(0).isoformat(),
                    'signal_bar': len(self.signal_data),
                    'signal_time': self.signal_data.datetime.datetime(0).isoformat()}

        def next(self):
            sb = max(int(self.p.signal_bar) - 1, 0)
            before_len = self._last_signal_len
            before_orders = len(self.events)
            record = self._point()
            record.update({'main': float(self.ind.main[-sb]),
                           'prev_main': float(self.ind.main[-(sb + 1)]),
                           'signal': float(self.ind.signal[-sb]),
                           'prev_signal': float(self.ind.signal[-(sb + 1)]),
                           'position': float(self.position.size)})
            super().next()
            if self._last_signal_len != before_len:
                self.comparisons.append(record)
            if len(self.events) != before_orders:
                self.rows.append(record)

        def buy(self, *args, **kwargs):
            self.events.append({**self._point(), 'event': 'buy_submit', 'position': float(self.position.size)})
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.events.append({**self._point(), 'event': 'sell_submit', 'position': float(self.position.size)})
            return super().sell(*args, **kwargs)

        def close(self, *args, **kwargs):
            self.events.append({**self._point(), 'event': 'close_submit', 'position': float(self.position.size)})
            return super().close(*args, **kwargs)

        def notify_order(self, order):
            if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.events.append({**self._point(), 'event': 'order_' + order.getstatusname(),
                                    'side': 'buy' if order.isbuy() else 'sell',
                                    'size': float(order.executed.size), 'price': float(order.executed.price),
                                    'value': float(order.executed.value), 'commission': float(order.executed.comm)})
            super().notify_order(order)

        def notify_trade(self, trade):
            if trade.isopen or trade.isclosed:
                self.events.append({**self._point(), 'event': 'trade_open' if trade.isopen else 'trade_close',
                                    'size': float(trade.size), 'price': float(trade.price),
                                    'pnl': float(trade.pnl), 'pnlcomm': float(trade.pnlcomm)})
            super().notify_trade(trade)

    c = bt.Cerebro(stdstats=True)
    c.broker.setcash(1_000_000)
    c.broker.setcommission(commission=0.0, margin=0.01, mult=100.0,
                           commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False)
    c.adddata(fixture.Mt5PandasFeed(dataname=data.copy(), timeframe=bt.TimeFrame.Minutes, compression=15))
    c.adddata(fixture.Mt5PandasFeed(dataname=signal_data.copy(), timeframe=bt.TimeFrame.Minutes, compression=240))
    c.addstrategy(Instrumented, rperiod=24, lsma_period=6, price='close', signal_bar=1,
                  stop_loss_points=1000, take_profit_points=2000, fixed_lot=0.1, point=0.01,
                  buy_pos_open=True, sell_pos_open=True, buy_pos_close=True, sell_pos_close=True)
    c.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trade')
    strat = c.run(runonce=True)[0]
    return {'final_value': c.broker.getvalue(), 'cash': c.broker.getcash(),
            'buy_count': strat.buy_count, 'sell_count': strat.sell_count,
            'trade_count': strat.trade_count, 'wins': strat.win_count, 'losses': strat.loss_count,
            'bar_num': strat.bar_num, 'signal_count': strat.signal_count,
            'comparisons': strat.comparisons, 'submissions': strat.rows, 'events': strat.events,
            'main': list(strat.ind.main.array), 'signal': list(strat.ind.signal.array),
            'price': list(signal_data['close'])}


def same(a, b):
    return (math.isnan(a) and math.isnan(b)) or math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


def main():
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    data = fixture.load_mt5_csv(fixture.DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    signal_data = fixture._build_signal_frame(data, 240)
    candidate = trigger.TriggerLine.next
    try:
        old = run(data, signal_data, baseline_next())
        new = run(data, signal_data, candidate)
    finally:
        trigger.TriggerLine.next = candidate
    changed = {name: [i for i, (a, b) in enumerate(zip(old[name], new[name])) if not same(a, b)]
               for name in ('main', 'signal')}
    event_a, event_b = old['events'], new['events']
    common_prefix = next((i for i, (a, b) in enumerate(zip(event_a, event_b)) if a != b),
                         min(len(event_a), len(event_b)))
    common_suffix = 0
    while (common_suffix < min(len(event_a), len(event_b)) - common_prefix and
           event_a[-common_suffix - 1] == event_b[-common_suffix - 1]):
        common_suffix += 1
    first = changed['signal'][0]
    previous, current = old['main'][first - 1], new['main'][first]
    prices = new['price']
    previous_ref = 6.0 / (24 * 25.0) * sum(
        (24 - lag - 25.0 / 3.0) * prices[first - 1 - lag] for lag in range(24))
    expected = previous_ref + (current - previous_ref) * 2.0 / 7.0
    def meta(x):
        return {k: x[k] for k in ('final_value', 'cash', 'buy_count', 'sell_count',
                                   'trade_count', 'wins', 'losses', 'bar_num', 'signal_count')}
    out = {'bars': [len(data), len(signal_data)], 'old': meta(old), 'new': meta(new),
           'changed_indices': changed, 'changed_first_signal': {'index': first,
               'signal_time': signal_data.index[first].isoformat(), 'old_nan': math.isnan(old['signal'][first]),
               'new': new['signal'][first], 'previous_output_nan': math.isnan(previous),
               'independent_previous_main': previous_ref, 'current_main': current,
               'independent_expected_signal': expected},
           'comparisons_first_old': old['comparisons'][:3], 'comparisons_first_new': new['comparisons'][:3],
           'events': {'old_count': len(event_a), 'new_count': len(event_b),
                      'common_prefix': common_prefix, 'common_suffix': common_suffix,
                      'old_distinct': event_a[common_prefix:len(event_a)-common_suffix if common_suffix else None],
                      'new_distinct': event_b[common_prefix:len(event_b)-common_suffix if common_suffix else None]}}
    print(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=True))


if __name__ == '__main__':
    main()

"""Backbone extreme-tracking layer strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Reversals from recent extremes (extreme highs or lows) can trigger strong breakout momentum. Adding position layers allows the system to ride and compound trends as they expand.
    - **Extreme Tracking**:
        - Establishes local maximum (`bid_max`) and minimum (`ask_min`) price levels while flat.
        - Trigger long/short once close price breaks down or up from these extremes by more than `trailing_stop` pips.
    - **Layer Compound Sizing (Scale-in)**:
        - Allows building up to `ntmax` (10) position layers as the trend persists.
        - Lot sizes are dynamically calculated based on capital, maximum risk fraction, stop loss pips, and current layered size.

Strategy Logic:
    1. **Initialization**: Configures scaling thresholds (`max_risk`, `ntmax`, `stop_loss`, `take_profit`, `trailing_stop`) and trading limits.
    2. **Extreme Updates**:
        - While flat, continuously tracks `bid_max` and `ask_min`. Sets `last_position` indicator when prices break out.
    3. **Position Entry & Layering**:
        - Submits initial buy/sell layer of size dynamically calculated by risk parameters.
        - Continues to add layers (`_check_add_or_first_entry`) if trend expands in the same direction.
    4. **Trailing Protection & Take Profit**:
        - Smoothly moves stop loss levels (`stop_price`) of active layers using `trailing_stop` distance.
        - Continuously monitors high/low prices against layer SL/TP parameters to close hit layers.
    5. **Reporting**: Extracts Sharpe ratio, net returns, drawdowns, win rate, and total executed transactions.
"""
from __future__ import annotations
import math
from pathlib import Path
import io
import argparse
import datetime
import sys
import backtrader as bt
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'backbone',
        'source_ea': 'ea/0689_BACKBONE/backbone.mq5',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'M15',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
    },
    'params': {
        'max_risk': 10.0,
        'ntmax': 10,
        'take_profit': 170,
        'stop_loss': 40,
        'trailing_stop': 300,
        'point': 0.01,
        'price_digits': 2,
        'contract_size': 100.0,
        'lot_step': 0.01,
        'lot_min': 0.01,
        'lot_max': 100.0,
        'leverage': 100.0,
    },
    'backtest': {
        'initial_cash': 1000000,
        'commission': 0.0,
        'margin': 0.01,
        'multiplier': 100.0,
        'commission_type': 'fixed',
        'stocklike': False,
    },
}


def _resolve_repo_paths(node):
    """Replace '{repo}' placeholder in config string values with absolute repo path."""
    if isinstance(node, dict):
        return {k: _resolve_repo_paths(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_repo_paths(v) for v in node]
    if isinstance(node, str):
        return node.replace('{repo}', str(_REPO))
    return node


def load_config(*args, **kwargs):
    """Inlined config (was config.yaml). Accepts any args for compatibility with strategies that pass a path."""
    import copy
    return _resolve_repo_paths(copy.deepcopy(_CONFIG))





def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Loads MT5 CSV data and parses it into a Pandas DataFrame.

    Cleans double quotes, strips whitespaces, and aligns the datetime index. Optionally shifts K-line datetime
    and filters by date range.

    Args:
        filepath (str or Path): Path to the CSV data file.
        fromdate (datetime, optional): Start date filter. Defaults to None.
        todate (datetime, optional): End date filter. Defaults to None.
        bar_shift_minutes (int, optional): Number of minutes to shift datetime index. Defaults to 0.

    Returns:
        pd.DataFrame: Processed OHLCV DataFrame indexed by datetime.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
        df['openinterest'] = 0
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    """Custom Pandas Data Feed for MT5 CSV format.

    Maps MT5 CSV columns (open, high, low, close, volume, openinterest) to Backtrader-compatible fields.
    """
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class BackboneStrategy(bt.Strategy):
    """Backbone Multi-layered Extreme Tracking Breakout Strategy.

    Tracks price extremes and scales into position layers as momentum expands.
    Manages trailing protection and take profits independently for each active layer.
    """
    params = dict(
        max_risk=0.5,
        ntmax=10,
        take_profit=170,
        stop_loss=40,
        trailing_stop=300,
        point=0.01,
        price_digits=2,
        contract_size=100.0,
        lot_step=0.01,
        lot_min=0.01,
        lot_max=100.0,
        leverage=100.0,
    )

    def __init__(self):
        """Initializes tracking extremes, active layers list, order state, and performance counters."""
        self.data0 = self.datas[0]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.layers = []
        self.pending_order = None
        self.pending_action = None
        self.last_position = 0
        self.bid_max = 0.0
        self.ask_min = float('inf')

    def log(self, text):
        """Logs strategy events with current datetime.

        Args:
            text (str): Log message.
        """
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _distance_unit(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _current_price(self):
        return float(self.data0.close[0])

    def _normalize_size(self, size):
        size = round(float(size) / float(self.p.lot_step), 0) * float(self.p.lot_step)
        size = max(size, float(self.p.lot_min))
        size = min(size, float(self.p.lot_max))
        return round(size, 2)

    def _calc_volume(self, total):
        ntmax = max(int(self.p.ntmax), 1)
        denominator = ntmax / max(float(self.p.max_risk), 1e-9) - float(total)
        if denominator <= 0:
            return 0.0
        frac = 1.0 / denominator
        stop_distance = float(self.p.stop_loss) * self._distance_unit()
        if stop_distance <= 0:
            return 0.0
        risk_budget = float(self.broker.getcash()) * frac
        risk_per_lot = stop_distance * float(self.p.contract_size)
        if risk_per_lot <= 0:
            return 0.0
        volume = risk_budget / risk_per_lot
        return self._normalize_size(volume)

    def _layer_stop(self, side, entry_price):
        if float(self.p.stop_loss) <= 0:
            return None
        distance = float(self.p.stop_loss) * self._distance_unit()
        if side == 'buy':
            return round(entry_price - distance, self.p.price_digits)
        return round(entry_price + distance, self.p.price_digits)

    def _layer_take_profit(self, side, entry_price):
        if float(self.p.take_profit) <= 0:
            return None
        distance = float(self.p.take_profit) * self._distance_unit()
        if side == 'buy':
            return round(entry_price + distance, self.p.price_digits)
        return round(entry_price - distance, self.p.price_digits)

    def _position_side(self):
        if not self.position:
            return None
        return 'buy' if self.position.size > 0 else 'sell'

    def _submit_open(self, side, size):
        if self.pending_order is not None or size <= 0:
            return False
        self.signal_count += 1
        self.pending_action = {'type': 'open', 'side': side, 'size': size}
        self.pending_order = self.buy(size=size) if side == 'buy' else self.sell(size=size)
        self.log(f'submit {side} size={size:.2f}')
        return True

    def _submit_close(self, layer_indexes, reason):
        if self.pending_order is not None or not layer_indexes:
            return False
        close_size = sum(self.layers[idx]['size'] for idx in layer_indexes)
        if close_size <= 0:
            return False
        self.pending_action = {
            'type': 'close_layers',
            'indexes': sorted(layer_indexes),
            'reason': reason,
        }
        side = self._position_side()
        self.pending_order = self.sell(size=close_size) if side == 'buy' else self.buy(size=close_size)
        self.log(f'submit close size={close_size:.2f} reason={reason} layers={layer_indexes}')
        return True

    def _update_initial_extremes(self):
        price = self._current_price()
        if self.last_position != 0:
            return
        if price > self.bid_max:
            self.bid_max = price
        if price < self.ask_min:
            self.ask_min = price
        threshold = float(self.p.trailing_stop) * self._distance_unit()
        if threshold <= 0:
            return
        if price < self.bid_max - threshold:
            self.last_position = -1
        if price > self.ask_min + threshold:
            self.last_position = 1

    def _check_add_or_first_entry(self):
        total = len(self.layers)
        if total >= int(self.p.ntmax):
            return False
        size = self._calc_volume(total)
        if size <= 0:
            return False
        if (self.last_position == -1 and total == 0) or (self.last_position == 1 and total > 0):
            self.last_position = 1
            return self._submit_open('buy', size)
        if (self.last_position == 1 and total == 0) or (self.last_position == -1 and total > 0):
            self.last_position = -1
            return self._submit_open('sell', size)
        return False

    def _update_layer_trailing(self):
        if not self.layers or float(self.p.trailing_stop) <= 0:
            return
        distance = float(self.p.trailing_stop) * self._distance_unit()
        price = self._current_price()
        for layer in self.layers:
            if layer['side'] == 'buy':
                if price - layer['entry_price'] > distance:
                    candidate = round(price - distance, self.p.price_digits)
                    if layer['stop_price'] is None or candidate > layer['stop_price']:
                        layer['stop_price'] = candidate
            else:
                if layer['entry_price'] - price > distance:
                    candidate = round(price + distance, self.p.price_digits)
                    if layer['stop_price'] is None or candidate < layer['stop_price']:
                        layer['stop_price'] = candidate

    def _check_layer_risk(self):
        if not self.layers or self.pending_order is not None:
            return False
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        to_close = []
        reason = None
        for idx, layer in enumerate(self.layers):
            if layer['side'] == 'buy':
                stop_hit = layer['stop_price'] is not None and low <= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and high >= layer['take_profit_price']
            else:
                stop_hit = layer['stop_price'] is not None and high >= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and low <= layer['take_profit_price']
            if stop_hit or take_hit:
                to_close.append(idx)
                if reason is None:
                    reason = 'take_profit' if take_hit and not stop_hit else 'stop_loss'
        if to_close:
            return self._submit_close(to_close, reason or 'risk_exit')
        return False

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Coordinates extreme price tracking, trailing stop updates, active layer protection checks,
        and scales into new layers if conditions allow.
        """
        self.bar_num += 1
        if len(self.data0) < 2:
            return
        self._update_initial_extremes()
        self._update_layer_trailing()
        if self._check_layer_risk():
            return
        if self.pending_order is not None:
            return
        self._check_add_or_first_entry()

    def notify_order(self, order):
        """Tracks order status and updates extreme boundaries and layers for completed transactions.

        Args:
            order (bt.Order): Backtrader order status notification object.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        action = self.pending_action if self.pending_order is not None and order.ref == self.pending_order.ref else None
        if order.status == bt.Order.Completed and action is not None:
            self.completed_order_count += 1
            if action['type'] == 'open':
                side = action['side']
                entry_price = float(order.executed.price)
                layer = {
                    'side': side,
                    'size': abs(float(order.executed.size)),
                    'entry_price': entry_price,
                    'stop_price': self._layer_stop(side, entry_price),
                    'take_profit_price': self._layer_take_profit(side, entry_price),
                }
                self.layers.append(layer)
                if side == 'buy':
                    self.buy_count += 1
                    self.last_position = 1
                else:
                    self.sell_count += 1
                    self.last_position = -1
                self.log(f'{side} filled price={entry_price:.2f} size={layer["size"]:.2f} sl={layer["stop_price"]} tp={layer["take_profit_price"]}')
            elif action['type'] == 'close_layers':
                remaining = []
                closed_pnl = 0.0
                fill_price = float(order.executed.price)
                for idx, layer in enumerate(self.layers):
                    if idx in action['indexes']:
                        if layer['side'] == 'buy':
                            closed_pnl += (fill_price - layer['entry_price']) * layer['size'] * float(self.p.contract_size)
                        else:
                            closed_pnl += (layer['entry_price'] - fill_price) * layer['size'] * float(self.p.contract_size)
                    else:
                        remaining.append(layer)
                self.layers = remaining
                if not self.layers:
                    self.last_position = 0
                    self.bid_max = 0.0
                    self.ask_min = float('inf')
                self.log(f'close filled price={fill_price:.2f} reason={action["reason"]} remaining_layers={len(self.layers)} pnl={closed_pnl:.2f}')
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.log(f'order failed status={order.getstatusname()}')
        if self.pending_order is not None and order.ref == self.pending_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.pending_order = None
            self.pending_action = None

    def notify_trade(self, trade):
        """Logs trade closure and records trade win/loss statistics.

        Args:
            trade (bt.Trade): Backtrader trade notification object.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')



BASE_DIR = Path(__file__).resolve().parent

WORKSPACE_DIR = BASE_DIR.parents[2]
LOCAL_BACKTRADER_REPO = WORKSPACE_DIR / 'backtrader'
if LOCAL_BACKTRADER_REPO.exists() and str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))



MINUTES_PER_TRADING_YEAR = 24 * 60 * 252



def resolve_data_path(filename):
    """Resolves target data file path relative to strategy directory.

    Args:
        filename (str): Name or path string of the data file.

    Returns:
        Path: Absolute path to the existing data file.

    Raises:
        FileNotFoundError: If the resolved path does not exist.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Prepares and loads historical data frame based on configuration parameters.

    Args:
        config (dict): Strategy configuration dictionary containing data parameters.

    Returns:
        dict: Preprocessed data frame and datetime filters.

    Raises:
        ValueError: If loaded data frame is empty.
    """
    data_cfg = config['data']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    df = load_mt5_csv(
        resolve_data_path(data_cfg['file']),
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )
    if df.empty:
        raise ValueError('Loaded data frame is empty')
    print(f'Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}')
    return {'data': df, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frame):
    """Builds and configures the Backtrader Cerebro backtesting engine.

    Sets initial capital, commissions, margin, data feeds, strategy instance, and analytical monitors.

    Args:
        config (dict): Configuration dictionary containing backtest parameters.
        frame (dict): Loaded historical data frame dictionary with datetime filters.

    Returns:
        bt.Cerebro: Fully configured backtesting engine instance.
    """
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type', 'fixed') == 'fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(
        commission=bt_cfg['commission'],
        margin=bt_cfg['margin'],
        mult=bt_cfg['multiplier'],
        commtype=comm_type,
        stocklike=bt_cfg.get('stocklike', False),
    )
    feed = Mt5PandasFeed(
        dataname=frame['data'][['open', 'high', 'low', 'close', 'volume', 'openinterest']],
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
    )
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(BackboneStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Extracts performance metrics from completed strategy and engine analyzer outputs.

    Args:
        strat (bt.Strategy): Executed strategy instance.
        cerebro (bt.Cerebro): Completed backtesting engine.
        frame (dict): Loaded historical data frame dictionary.
        config (dict): Strategy configuration dictionary.

    Returns:
        dict: Performance summary statistics including Sharpe, return, drawdowns, and trade counts.
    """
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    total_trades = trades.get('total', {}).get('closed', won + lost)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'fromdate': frame['fromdate'],
        'todate': frame['todate'],
        'bars': len(frame['data']),
        'bar_num': strat.bar_num,
        'signal_count': strat.signal_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'trade_count': strat.trade_count,
        'completed_orders': strat.completed_order_count,
        'rejected_orders': strat.rejected_order_count,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1) * 100,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100) if total_trades else 0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sqn': sqn.get('sqn'),
    }



def run(plot=False):
    """Orchestrates strategy loading, execution, evaluation, and optional plotting.

    Args:
        plot (bool, optional): Whether to plot backtest chart. Defaults to False.

    Returns:
        tuple: (results, metrics, cerebro) containing strategy results, metrics dict, and engine.
    """
    config = load_config()
    frame = load_backtest_frame(config)
    cerebro = build_cerebro(config, frame)
    print('\nStarting backtest...')
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, config)

    if plot:
        cerebro.plot()
    return results, metrics, cerebro


def _close(actual, expected, *, tol, key):
    """Assert ``actual`` is finite and within ``tol`` of ``expected``."""
    assert actual is not None, f"{key}: expected={expected}, got=None"
    a = float(actual)
    assert math.isfinite(a), f"{key}: expected={expected}, got non-finite {actual}"
    assert abs(a - float(expected)) <= tol, (
        f"{key}: expected={expected}, got={a} (tol={tol})"
    )


def test_228_0229_0689_backbone() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0229_0689_backbone.
    """
    # Capture metrics by hooking extract_metrics() (or similar) and invoking the
    # original main()/run(). This reuses whatever loader / build_cerebro /
    # metrics-extraction signatures the strategy used internally.
    captured = {}

    import sys as _sys
    _mod = _sys.modules[__name__]

    # Hook any plausible metrics-extraction function.
    _hook_targets = []
    _metric_names = (
        "extract_metrics", "summarize", "build_metrics", "compute_metrics",
        "calculate_metrics", "collect_metrics", "gather_metrics", "extract_results",
    )
    for _name in _metric_names:
        _orig = getattr(_mod, _name, None)
        if callable(_orig):
            def _make_hook(orig):
                def _hook(*a, **kw):
                    m = orig(*a, **kw)
                    if isinstance(m, dict) and m and "metrics" not in captured:
                        captured["metrics"] = m
                    return m
                return _hook
            setattr(_mod, _name, _make_hook(_orig))
            _hook_targets.append((_name, _orig))

    # Force runonce=True for the cerebro.run() call inside main().
    import backtrader as _bt
    _orig_run = _bt.Cerebro.run
    def _forced_runonce(self, *args, **kwargs):
        kwargs["runonce"] = True
        return _orig_run(self, *args, **kwargs)
    _bt.Cerebro.run = _forced_runonce

    # Strip pytest argv so argparse-based main() functions don't see them.
    _saved_argv = _sys.argv
    _sys.argv = [_sys.argv[0]]

    try:
        try:
            if hasattr(_mod, "main") and callable(_mod.main):
                _mod.main()
            elif hasattr(_mod, "run") and callable(_mod.run):
                result = _mod.run()
                if isinstance(result, dict) and "metrics" not in captured:
                    captured["metrics"] = result
                elif isinstance(result, (list, tuple)):
                    for item in result:
                        if isinstance(item, dict) and "metrics" not in captured:
                            captured["metrics"] = item
                            break
            else:
                raise RuntimeError("Neither main() nor run() found in inlined module")
        except SystemExit:
            pass
        except Exception:
            if "metrics" not in captured:
                raise
    finally:
        _bt.Cerebro.run = _orig_run
        for _name, _orig in _hook_targets:
            setattr(_mod, _name, _orig)
        _sys.argv = _saved_argv

    metrics = captured.get("metrics")
    assert metrics is not None, "no metrics captured during run"

    assert metrics.get('bar_num') == 6129, f"bar_num: expected=6129, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 446, f"buy_count: expected=446, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 591, f"sell_count: expected=591, got={metrics.get('sell_count')!r}"
    assert metrics.get('total_trades') == 1037, f"total_trades: expected=1037, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 1037, f"trade_count: expected=1037, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 541, f"won: expected=541, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 496, f"lost: expected=496, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('signal_count'), 1037.0, tol=1.037000e-03, key='signal_count')
    _close(metrics.get('completed_orders'), 2074.0, tol=2.074000e-03, key='completed_orders')
    _close(metrics.get('rejected_orders'), 2137.0, tol=2.137000e-03, key='rejected_orders')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 250645.0000000757, tol=2.506450e-01, key='final_value')
    _close(metrics.get('net_pnl'), -749354.9999999243, tol=7.493550e-01, key='net_pnl')
    _close(metrics.get('total_return_pct'), -74.93549999999243, tol=7.493550e-05, key='total_return_pct')
    _close(metrics.get('win_rate'), 52.169720347155256, tol=5.216972e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 0.9727786415384984, tol=1.000000e-06, key='profit_factor')
    _close(metrics.get('sharpe_ratio'), 3.1154024240642477, tol=3.115402e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), -100.0, tol=1.000000e-04, key='annual_return_pct')
    _close(metrics.get('max_drawdown'), 436.0014579915977, tol=4.360015e-04, key='max_drawdown')
    _close(metrics.get('sqn'), -0.274676005604032, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"

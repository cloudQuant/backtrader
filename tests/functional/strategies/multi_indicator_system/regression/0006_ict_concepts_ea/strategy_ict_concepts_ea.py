from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
import pandas as pd



def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class ICTConceptsEAStrategy(bt.Strategy):
    params = dict(
        risk_percent_per_trade=0.25,
        max_total_drawdown_percent=10.0,
        max_daily_drawdown_percent=5.0,
        initial_balance=5000.0,
        tp1_rr=1.0,
        tp2_rr=2.0,
        tp3_rr=3.0,
        partial_close_percent_tp1=50.0,
        partial_close_percent_tp2=25.0,
        partial_close_percent_tp3=25.0,
        move_sl_to_be_after_tp1=True,
        be_plus_pips=1,
        trailing_sl_pips=10.0,
        use_silver_bullet=True,
        sb_start_time='10:00',
        sb_end_time='11:00',
        use_2022_model=True,
        use_ote_entry=True,
        htf_ma_period=200,
        dol_lookback_bars=120,
        ndog_nwog_threshold=0.5,
        ote_lower_level=0.618,
        ote_upper_level=0.786,
        point_size=0.01,
        digits_factor=1.0,
        min_lot=0.01,
        lot_step=0.01,
        max_lot=100.0,
        multiplier=100.0,
        verbose=False,
    )

    def __init__(self):
        self.data_ltf = self.datas[0]
        self.data_htf = self.datas[1]
        self.htf_ma = bt.indicators.SimpleMovingAverage(self.data_htf.close, period=self.p.htf_ma_period)
        self.atr14 = bt.indicators.ATR(self.data_ltf, period=14)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.active_setup = None
        self.initial_volume = 0.0
        self.tp1_hit = False
        self.tp2_hit = False
        self.daily_start_equity = None
        self.daily_start_date = None
        self.debug_counts = {
            'trading_blocked': 0,
            'htf_bias_none': 0,
            'rates_missing': 0,
            'silver_window_open': 0,
            'silver_attempts': 0,
            'model_2022_attempts': 0,
            'liquidity_fail': 0,
            'mss_fail': 0,
            'fvg_fail': 0,
            'ndog_fail': 0,
            'price_outside_fvg': 0,
            'stop_loss_invalid': 0,
            'risk_invalid': 0,
            'setup_ready': 0,
        }

    def log(self, text):
        if not self.p.verbose:
            return
        dt = bt.num2date(self.data_ltf.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _current_dt(self):
        return bt.num2date(self.data_ltf.datetime[0])

    def _current_date(self):
        return self._current_dt().date()

    def _time_to_minutes(self, value):
        hh, mm = value.split(':')
        return int(hh) * 60 + int(mm)

    def _within_silver_bullet_window(self):
        now = self._current_dt().hour * 60 + self._current_dt().minute
        start = self._time_to_minutes(self.p.sb_start_time)
        end = self._time_to_minutes(self.p.sb_end_time)
        return start <= now < end

    def _update_daily_equity_anchor(self):
        current_date = self._current_date()
        if self.daily_start_date != current_date:
            self.daily_start_date = current_date
            self.daily_start_equity = self.broker.getvalue()

    def _trading_allowed(self):
        self._update_daily_equity_anchor()
        value = self.broker.getvalue()
        total_floor = float(self.p.initial_balance) * (1.0 - float(self.p.max_total_drawdown_percent) / 100.0)
        if value <= total_floor:
            return False
        if self.daily_start_equity is not None:
            daily_floor = self.daily_start_equity * (1.0 - float(self.p.max_daily_drawdown_percent) / 100.0)
            if value <= daily_floor:
                return False
        return True

    def _normalize_lot(self, lot):
        step = float(self.p.lot_step) if self.p.lot_step > 0 else 0.01
        lot = math.floor(lot / step) * step
        lot = min(max(lot, float(self.p.min_lot)), float(self.p.max_lot))
        return round(lot, 8)

    def _calculate_lot_size(self, stop_loss_price, entry_price):
        if self.p.risk_percent_per_trade <= 0:
            return float(self.p.min_lot)
        risk_amount = self.broker.getvalue() * (float(self.p.risk_percent_per_trade) / 100.0)
        stop_distance = abs(float(entry_price) - float(stop_loss_price))
        if stop_distance <= 0:
            return float(self.p.min_lot)
        risk_per_lot = stop_distance * float(self.p.multiplier)
        if risk_per_lot <= 0:
            return float(self.p.min_lot)
        return self._normalize_lot(risk_amount / risk_per_lot)

    def _get_rates(self, count):
        if len(self.data_ltf) < count:
            return None
        rates = []
        for i in range(count):
            rates.append({
                'open': float(self.data_ltf.open[-i]),
                'high': float(self.data_ltf.high[-i]),
                'low': float(self.data_ltf.low[-i]),
                'close': float(self.data_ltf.close[-i]),
            })
        return rates

    def _determine_htf_bias(self):
        if len(self.data_htf) < self.p.htf_ma_period + 2:
            return None
        current_price = float(self.data_ltf.close[0])
        ma_now = float(self.htf_ma[0])
        ma_prev = float(self.htf_ma[-1])
        if current_price > ma_now and ma_now > ma_prev:
            return 'buy'
        if current_price < ma_now and ma_now < ma_prev:
            return 'sell'
        return None

    def _fallback_bias(self):
        if len(self.data_ltf) < 2:
            return None
        if len(self.data_htf) >= self.p.htf_ma_period + 1:
            current_price = float(self.data_ltf.close[0])
            ma_now = float(self.htf_ma[0])
            if math.isfinite(ma_now):
                return 'buy' if current_price >= ma_now else 'sell'
        close0 = float(self.data_ltf.close[0])
        close1 = float(self.data_ltf.close[-1])
        if close0 > close1:
            return 'buy'
        if close0 < close1:
            return 'sell'
        return None

    def _find_nearest_liquidity_level(self, find_high):
        lookback = min(self.p.dol_lookback_bars, len(self.data_ltf) - 1)
        if lookback < 2:
            return 0.0
        values = [
            float(self.data_ltf.high[-i]) if find_high else float(self.data_ltf.low[-i])
            for i in range(1, lookback + 1)
        ]
        return max(values) if find_high else min(values)

    def _check_liquidity_sweep(self, liquidity_level, bias, rates):
        if liquidity_level == 0 or len(rates) < 2:
            return False
        current_price = rates[0]['close']
        if bias == 'buy' and current_price < liquidity_level and rates[1]['low'] <= liquidity_level:
            return True
        if bias == 'sell' and current_price > liquidity_level and rates[1]['high'] >= liquidity_level:
            return True
        return False

    def _check_mss(self, bias, rates):
        if len(rates) < 3:
            return False
        if bias == 'buy':
            return rates[0]['close'] > rates[1]['high'] and rates[1]['close'] < rates[2]['open']
        if bias == 'sell':
            return rates[0]['close'] < rates[1]['low'] and rates[1]['close'] > rates[2]['open']
        return False

    def _find_fvg(self, rates):
        for i in range(2, min(len(rates) - 1, 10)):
            if rates[i]['high'] < rates[i - 2]['low'] and rates[i - 1]['close'] > rates[i]['high']:
                return rates[i - 2]['low'], rates[i]['high']
            if rates[i]['low'] > rates[i - 2]['high'] and rates[i - 1]['close'] < rates[i]['low']:
                return rates[i]['low'], rates[i - 2]['high']
        return 0.0, 0.0

    def _check_ndog_nwog(self, rates):
        if len(rates) < 1 or len(self.atr14) < 1:
            return False
        threshold = float(self.atr14[0]) * float(self.p.ndog_nwog_threshold)
        return (rates[0]['high'] - rates[0]['low']) <= threshold

    def _calculate_entry_price(self, level1, level2):
        value_range = abs(level2 - level1)
        if not self.p.use_ote_entry:
            return (level1 + level2) / 2.0
        return level1 + value_range * float(self.p.ote_lower_level) if level1 < level2 else level1 - value_range * float(self.p.ote_lower_level)

    def _find_protective_stop_loss(self, rates, is_buy):
        subset = rates[: min(10, len(rates))]
        if not subset:
            return 0.0
        if is_buy:
            level = min(r['low'] for r in subset)
            return level - float(self.p.point_size) * float(self.p.digits_factor)
        level = max(r['high'] for r in subset)
        return level + float(self.p.point_size) * float(self.p.digits_factor)

    def _build_setup(self, bias, strategy_name, rates, liquidity_bias):
        liquidity_level = self._find_nearest_liquidity_level(liquidity_bias == 'sell')
        liquidity_swept = self._check_liquidity_sweep(liquidity_level, liquidity_bias, rates)
        mss_confirmed = self._check_mss(bias, rates)
        fvg_high, fvg_low = self._find_fvg(rates)
        is_ndog_nwog = self._check_ndog_nwog(rates)
        if not liquidity_swept:
            self.debug_counts['liquidity_fail'] += 1
            return None
        if not mss_confirmed:
            self.debug_counts['mss_fail'] += 1
            return None
        if not (fvg_high > 0 and fvg_low > 0):
            self.debug_counts['fvg_fail'] += 1
            return None
        if not is_ndog_nwog:
            self.debug_counts['ndog_fail'] += 1
            return None
        current_price = rates[0]['close']
        upper = max(fvg_high, fvg_low)
        lower = min(fvg_high, fvg_low)
        if not (lower <= current_price <= upper):
            self.debug_counts['price_outside_fvg'] += 1
            return None
        entry_price = self._calculate_entry_price(lower, upper)
        stop_loss_price = self._find_protective_stop_loss(rates, bias == 'buy')
        if stop_loss_price <= 0:
            self.debug_counts['stop_loss_invalid'] += 1
            return None
        risk = abs(entry_price - stop_loss_price)
        if risk <= 0:
            self.debug_counts['risk_invalid'] += 1
            return None
        tp1 = entry_price + risk * float(self.p.tp1_rr) if bias == 'buy' else entry_price - risk * float(self.p.tp1_rr)
        tp2 = entry_price + risk * float(self.p.tp2_rr) if bias == 'buy' else entry_price - risk * float(self.p.tp2_rr)
        tp3 = entry_price + risk * float(self.p.tp3_rr) if bias == 'buy' else entry_price - risk * float(self.p.tp3_rr)
        self.debug_counts['setup_ready'] += 1
        return {
            'strategy_name': strategy_name,
            'bias': bias,
            'entry_price': entry_price,
            'stop_loss_price': stop_loss_price,
            'tp1_price': tp1,
            'tp2_price': tp2,
            'tp3_price': tp3,
            'lot_size': self._calculate_lot_size(stop_loss_price, entry_price),
        }

    def _check_silver_bullet_entry(self, bias, rates):
        return self._build_setup(bias, 'SilverBullet', rates, bias)

    def _check_2022_model_entry(self, bias, rates):
        opposite_bias = 'buy' if bias == 'sell' else 'sell'
        return self._build_setup(bias, '2022Model', rates, opposite_bias)

    def _build_fallback_setup(self, bias, rates):
        if not rates:
            return None
        entry_price = float(self.data_ltf.close[0])
        atr = float(self.atr14[0]) if len(self.atr14) and math.isfinite(float(self.atr14[0])) else 0.0
        risk = max(atr, float(self.p.point_size) * float(self.p.digits_factor) * 50.0)
        if bias == 'buy':
            stop_loss_price = min(r['low'] for r in rates[: min(10, len(rates))]) - float(self.p.point_size) * float(self.p.digits_factor)
            if stop_loss_price >= entry_price:
                stop_loss_price = entry_price - risk
            tp1 = entry_price + risk * float(self.p.tp1_rr)
            tp2 = entry_price + risk * float(self.p.tp2_rr)
            tp3 = entry_price + risk * float(self.p.tp3_rr)
        else:
            stop_loss_price = max(r['high'] for r in rates[: min(10, len(rates))]) + float(self.p.point_size) * float(self.p.digits_factor)
            if stop_loss_price <= entry_price:
                stop_loss_price = entry_price + risk
            tp1 = entry_price - risk * float(self.p.tp1_rr)
            tp2 = entry_price - risk * float(self.p.tp2_rr)
            tp3 = entry_price - risk * float(self.p.tp3_rr)
        self.debug_counts['setup_ready'] += 1
        return {
            'strategy_name': 'FallbackBias',
            'bias': bias,
            'entry_price': entry_price,
            'stop_loss_price': stop_loss_price,
            'tp1_price': tp1,
            'tp2_price': tp2,
            'tp3_price': tp3,
            'lot_size': self._calculate_lot_size(stop_loss_price, entry_price),
        }

    def _partial_close(self, fraction):
        if not self.position:
            return
        size = abs(self.position.size) * fraction
        size = self._normalize_lot(size)
        if size >= float(self.p.min_lot) and size < abs(self.position.size):
            self.close(size=size)

    def _manage_open_trade(self):
        if not self.position or not self.active_setup:
            return
        high = float(self.data_ltf.high[0])
        low = float(self.data_ltf.low[0])
        current_close = float(self.data_ltf.close[0])
        is_buy = self.position.size > 0
        stop_price = self.active_setup['stop_loss_price']
        tp1_price = self.active_setup['tp1_price']
        tp2_price = self.active_setup['tp2_price']
        tp3_price = self.active_setup['tp3_price']
        hit_stop = low <= stop_price if is_buy else high >= stop_price
        hit_tp3 = high >= tp3_price if is_buy else low <= tp3_price
        if hit_stop:
            self.close()
            self.active_setup = None
            self.log('STOP LOSS HIT')
            return
        if not self.tp1_hit:
            hit_tp1 = high >= tp1_price if is_buy else low <= tp1_price
            if hit_tp1:
                self._partial_close(float(self.p.partial_close_percent_tp1) / 100.0)
                self.tp1_hit = True
                if self.p.move_sl_to_be_after_tp1:
                    be_level = self.position.price + (float(self.p.be_plus_pips) * float(self.p.point_size) * float(self.p.digits_factor) * (1 if is_buy else -1))
                    if (is_buy and be_level > self.active_setup['stop_loss_price']) or (not is_buy and be_level < self.active_setup['stop_loss_price']):
                        self.active_setup['stop_loss_price'] = be_level
        if self.tp1_hit and not self.tp2_hit:
            hit_tp2 = high >= tp2_price if is_buy else low <= tp2_price
            if hit_tp2:
                self._partial_close(float(self.p.partial_close_percent_tp2) / 100.0)
                self.tp2_hit = True
                new_sl = current_close - float(self.p.trailing_sl_pips) * float(self.p.point_size) * float(self.p.digits_factor) if is_buy else current_close + float(self.p.trailing_sl_pips) * float(self.p.point_size) * float(self.p.digits_factor)
                if (is_buy and new_sl > self.active_setup['stop_loss_price']) or (not is_buy and new_sl < self.active_setup['stop_loss_price']):
                    self.active_setup['stop_loss_price'] = new_sl
        if self.tp2_hit:
            new_sl = current_close - float(self.p.trailing_sl_pips) * float(self.p.point_size) * float(self.p.digits_factor) if is_buy else current_close + float(self.p.trailing_sl_pips) * float(self.p.point_size) * float(self.p.digits_factor)
            if (is_buy and new_sl > self.active_setup['stop_loss_price']) or (not is_buy and new_sl < self.active_setup['stop_loss_price']):
                self.active_setup['stop_loss_price'] = new_sl
        if hit_tp3 and self.position:
            self.close()
            self.active_setup = None
            self.log('TP3 HIT')

    def _check_for_entry_signals(self):
        if not self._trading_allowed():
            self.debug_counts['trading_blocked'] += 1
            return None
        bias = self._determine_htf_bias()
        if bias is None:
            self.debug_counts['htf_bias_none'] += 1
            bias = self._fallback_bias()
            if bias is None:
                return None
        rates = self._get_rates(20)
        if rates is None:
            self.debug_counts['rates_missing'] += 1
            return None
        if self.p.use_silver_bullet and self._within_silver_bullet_window():
            self.debug_counts['silver_window_open'] += 1
            self.debug_counts['silver_attempts'] += 1
            setup = self._check_silver_bullet_entry(bias, rates)
            if setup is not None:
                return setup
        if self.p.use_2022_model:
            self.debug_counts['model_2022_attempts'] += 1
            setup = self._check_2022_model_entry(bias, rates)
            if setup is not None:
                return setup
        return self._build_fallback_setup(bias, rates)

    def next(self):
        self.bar_num += 1
        self._update_daily_equity_anchor()
        if self.position:
            self._manage_open_trade()
            return
        if self.entry_order is not None:
            return
        setup = self._check_for_entry_signals()
        if setup is None:
            return
        self.active_setup = setup
        self.initial_volume = setup['lot_size']
        self.tp1_hit = False
        self.tp2_hit = False
        if setup['bias'] == 'buy':
            self.entry_order = self.buy(size=setup['lot_size'])
            self.buy_count += 1
            self.log('OPEN BUY')
        else:
            self.entry_order = self.sell(size=setup['lot_size'])
            self.sell_count += 1
            self.log('OPEN SELL')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.entry_order = None
                self.active_setup = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self.active_setup = None
            self.tp1_hit = False
            self.tp2_hit = False
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')

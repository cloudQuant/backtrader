"""Line Operations Test Cases

测试 backtrader 指标之间的向量操作（加减乘除）
使用随机生成的数据，设定seed确保可重复性

测试用例:
1. MACD EMA 指标计算 (ema1 - ema2, dif - dea, * 2)
2. Keltner Channel 指标计算 ((high + low + close) / 3, middle_line + atr * mult)
3. TimeLine + SMA 指标计算
4. Highest/Lowest 指标计算
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import random
import math

import backtrader as bt


# ============================================================================
# 辅助函数：生成随机 OHLCV 数据
# ============================================================================
def generate_random_ohlcv_data(num_bars=100, seed=42):
    """生成随机的 OHLCV 数据
    
    Args:
        num_bars: 生成的bar数量
        seed: 随机种子，确保可重复性
        
    Returns:
        list of dict: OHLCV 数据列表
    """
    random.seed(seed)
    
    data = []
    base_price = 100.0
    base_date = datetime.datetime(2020, 1, 1, 9, 0, 0)
    
    for i in range(num_bars):
        # 生成随机价格变动
        change = random.uniform(-2, 2)
        base_price = max(50, base_price + change)  # 确保价格不会太低
        
        # 生成 OHLC
        open_price = base_price + random.uniform(-1, 1)
        high_price = max(open_price, base_price) + random.uniform(0, 2)
        low_price = min(open_price, base_price) - random.uniform(0, 2)
        close_price = base_price + random.uniform(-1, 1)
        
        # 确保 high >= open, close 且 low <= open, close
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price)
        
        volume = random.randint(1000, 10000)
        
        dt = base_date + datetime.timedelta(minutes=i)
        
        data.append({
            'datetime': dt,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume,
            'openinterest': 0
        })
    
    return data


class RandomDataFeed(bt.feeds.DataBase):
    """自定义数据源，使用随机生成的数据"""
    
    params = (
        ('data_list', None),
    )
    
    def __init__(self):
        super(RandomDataFeed, self).__init__()
        self._data_list = self.p.data_list or []
        self._idx = 0
    
    def start(self):
        super(RandomDataFeed, self).start()
        self._idx = 0
    
    def _load(self):
        if self._idx >= len(self._data_list):
            return False
        
        bar = self._data_list[self._idx]
        self.lines.datetime[0] = bt.date2num(bar['datetime'])
        self.lines.open[0] = bar['open']
        self.lines.high[0] = bar['high']
        self.lines.low[0] = bar['low']
        self.lines.close[0] = bar['close']
        self.lines.volume[0] = bar['volume']
        self.lines.openinterest[0] = bar['openinterest']
        
        self._idx += 1
        return True


# ============================================================================
# 测试用例 1: MACD EMA 指标计算
# ============================================================================
class MacdEmaTestStrategy(bt.Strategy):
    """测试 MACD EMA 指标的向量操作
    
    self.ema_1 - self.ema_2 (指标减指标)
    self.dif - self.dea (指标减指标)
    (self.dif - self.dea) * 2 (指标乘常数)
    """
    params = (
        ("period_me1", 10),
        ("period_me2", 20),
        ("period_dif", 9),
    )
    
    def __init__(self):
        self.bar_num = 0
        self.recorded_values = []
        
        # MACD 指标计算
        self.ema_1 = bt.indicators.ExponentialMovingAverage(
            self.datas[0].close, period=self.p.period_me1
        )
        self.ema_2 = bt.indicators.ExponentialMovingAverage(
            self.datas[0].close, period=self.p.period_me2
        )
        self.dif = self.ema_1 - self.ema_2
        self.dea = bt.indicators.ExponentialMovingAverage(
            self.dif, period=self.p.period_dif
        )
        self.macd = (self.dif - self.dea) * 2
    
    def next(self):
        self.bar_num += 1
        
        # 记录指标值（跳过warmup期间的NaN值）
        ema1_val = self.ema_1[0]
        ema2_val = self.ema_2[0]
        dif_val = self.dif[0]
        dea_val = self.dea[0]
        macd_val = self.macd[0]
        
        # 检查是否为有效值
        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))
        
        if is_valid(ema1_val) and is_valid(ema2_val) and is_valid(dif_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'close': self.datas[0].close[0],
                'ema_1': round(ema1_val, 6),
                'ema_2': round(ema2_val, 6),
                'dif': round(dif_val, 6),
                'dea': round(dea_val, 6) if is_valid(dea_val) else None,
                'macd': round(macd_val, 6) if is_valid(macd_val) else None,
            })


# ============================================================================
# 测试用例 2: Keltner Channel 指标计算
# ============================================================================
class KeltnerTestStrategy(bt.Strategy):
    """测试 Keltner Channel 指标的向量操作
    
    (high + low + close) / 3 (多个line相加除以常数)
    middle_line + atr * mult (指标加指标乘常数)
    middle_line - atr * mult (指标减指标乘常数)
    """
    params = (
        ("avg_period", 20),
        ("atr_multi", 2),
    )
    
    def __init__(self):
        self.bar_num = 0
        self.recorded_values = []
        
        # Keltner Channel 指标计算
        self.middle_price = (
            self.datas[0].high + self.datas[0].low + self.datas[0].close
        ) / 3
        self.middle_line = bt.indicators.SMA(
            self.middle_price, period=self.p.avg_period
        )
        self.atr = bt.indicators.AverageTrueRange(
            self.datas[0], period=self.p.avg_period
        )
        self.upper_line = self.middle_line + self.atr * self.p.atr_multi
        self.lower_line = self.middle_line - self.atr * self.p.atr_multi
    
    def next(self):
        self.bar_num += 1
        
        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))
        
        middle_price_val = self.middle_price[0]
        middle_line_val = self.middle_line[0]
        atr_val = self.atr[0]
        upper_val = self.upper_line[0]
        lower_val = self.lower_line[0]
        
        if is_valid(middle_line_val) and is_valid(atr_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'middle_price': round(middle_price_val, 6),
                'middle_line': round(middle_line_val, 6),
                'atr': round(atr_val, 6),
                'upper_line': round(upper_val, 6),
                'lower_line': round(lower_val, 6),
            })


# ============================================================================
# 测试用例 3: TimeLine + SMA 指标计算
# ============================================================================
class TimeLine(bt.Indicator):
    """分时均价线指标"""
    lines = ('day_avg_price',)
    
    def __init__(self):
        self.price_sum = 0.0
        self.price_count = 0
    
    def next(self):
        self.price_count += 1
        self.price_sum += self.data.close[0]
        self.lines.day_avg_price[0] = self.price_sum / self.price_count


class TimeLineSmaTestStrategy(bt.Strategy):
    """测试 TimeLine + SMA 指标"""
    params = (
        ("ma_period", 20),
    )
    
    def __init__(self):
        self.bar_num = 0
        self.recorded_values = []
        
        self.day_avg_price = TimeLine(self.datas[0])
        self.ma_value = bt.indicators.SMA(
            self.datas[0].close, period=self.p.ma_period
        )
    
    def next(self):
        self.bar_num += 1
        
        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))
        
        avg_price_val = self.day_avg_price[0]
        ma_val = self.ma_value[0]
        
        if is_valid(avg_price_val) and is_valid(ma_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'close': round(self.datas[0].close[0], 6),
                'day_avg_price': round(avg_price_val, 6),
                'ma_value': round(ma_val, 6),
            })


# ============================================================================
# 测试用例 4: Highest/Lowest 指标计算
# ============================================================================
class HighestLowestTestStrategy(bt.Strategy):
    """测试 Highest/Lowest 指标"""
    params = (
        ("period", 20),
    )
    
    def __init__(self):
        self.bar_num = 0
        self.recorded_values = []
        
        self.highest_high = bt.indicators.Highest(
            self.datas[0].high, period=self.p.period
        )
        self.lowest_low = bt.indicators.Lowest(
            self.datas[0].low, period=self.p.period
        )
    
    def next(self):
        self.bar_num += 1
        
        def is_valid(v):
            return v is not None and not (isinstance(v, float) and math.isnan(v))
        
        highest_val = self.highest_high[0]
        lowest_val = self.lowest_low[0]
        
        if is_valid(highest_val) and is_valid(lowest_val):
            self.recorded_values.append({
                'bar_num': self.bar_num,
                'high': round(self.datas[0].high[0], 6),
                'low': round(self.datas[0].low[0], 6),
                'highest_high': round(highest_val, 6),
                'lowest_low': round(lowest_val, 6),
            })


# ============================================================================
# 测试函数
# ============================================================================
def run_strategy(strategy_class, num_bars=100, seed=42, **kwargs):
    """运行策略并返回策略实例"""
    cerebro = bt.Cerebro()
    
    # 生成随机数据
    data_list = generate_random_ohlcv_data(num_bars=num_bars, seed=seed)
    data = RandomDataFeed(data_list=data_list)
    cerebro.adddata(data)
    
    # 添加策略
    cerebro.addstrategy(strategy_class, **kwargs)
    
    # 运行
    results = cerebro.run()
    return results[0]


def test_macd_ema_line_operations():
    """测试 MACD EMA 指标的向量操作"""
    strategy = run_strategy(MacdEmaTestStrategy, num_bars=100, seed=42)
    
    # 验证bar数量 (由于指标warmup期，实际进入next的bar数量会少于100)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")
    
    # 验证有记录的值
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"
    
    # 预期值 (从master版本获取) - 验证特定bar的关键指标值
    EXPECTED_BAR_NUM = 73
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'ema_1': 103.716294, 'ema_2': 102.189275, 
        'dif': 1.527019, 'dea': 0.819102, 'macd': 1.415833
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 73, 'ema_1': 102.306701, 'ema_2': 101.658218,
        'dif': 0.648483, 'dea': 0.388373, 'macd': 0.520219
    }
    
    # 获取实际记录
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None
    
    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")
    
    # 验证bar数量
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"
    
    # 验证第一条记录的 ema_1 值
    if first_valid:
        assert abs(first_valid['ema_1'] - EXPECTED_FIRST_RECORD['ema_1']) < 1e-4, \
            f"First ema_1 mismatch: expected {EXPECTED_FIRST_RECORD['ema_1']}, got {first_valid['ema_1']}"
        assert abs(first_valid['ema_2'] - EXPECTED_FIRST_RECORD['ema_2']) < 1e-4, \
            f"First ema_2 mismatch: expected {EXPECTED_FIRST_RECORD['ema_2']}, got {first_valid['ema_2']}"
        assert abs(first_valid['dif'] - EXPECTED_FIRST_RECORD['dif']) < 1e-4, \
            f"First dif mismatch: expected {EXPECTED_FIRST_RECORD['dif']}, got {first_valid['dif']}"
    
    # 验证最后一条记录的所有指标值
    if last_valid:
        assert abs(last_valid['ema_1'] - EXPECTED_LAST_RECORD['ema_1']) < 1e-4, \
            f"Last ema_1 mismatch: expected {EXPECTED_LAST_RECORD['ema_1']}, got {last_valid['ema_1']}"
        assert abs(last_valid['ema_2'] - EXPECTED_LAST_RECORD['ema_2']) < 1e-4, \
            f"Last ema_2 mismatch: expected {EXPECTED_LAST_RECORD['ema_2']}, got {last_valid['ema_2']}"
        assert abs(last_valid['dif'] - EXPECTED_LAST_RECORD['dif']) < 1e-4, \
            f"Last dif mismatch: expected {EXPECTED_LAST_RECORD['dif']}, got {last_valid['dif']}"
        if last_valid['dea'] is not None and EXPECTED_LAST_RECORD['dea'] is not None:
            assert abs(last_valid['dea'] - EXPECTED_LAST_RECORD['dea']) < 1e-4, \
                f"Last dea mismatch: expected {EXPECTED_LAST_RECORD['dea']}, got {last_valid['dea']}"
        if last_valid['macd'] is not None and EXPECTED_LAST_RECORD['macd'] is not None:
            assert abs(last_valid['macd'] - EXPECTED_LAST_RECORD['macd']) < 1e-4, \
                f"Last macd mismatch: expected {EXPECTED_LAST_RECORD['macd']}, got {last_valid['macd']}"


def test_keltner_line_operations():
    """测试 Keltner Channel 指标的向量操作"""
    strategy = run_strategy(KeltnerTestStrategy, num_bars=100, seed=42)
    
    # 验证bar数量 (由于指标warmup期，实际进入next的bar数量会少于100)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")
    
    # 验证有记录的值
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"
    
    # 预期值 (从master版本获取)
    EXPECTED_BAR_NUM = 80
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'middle_price': 102.743291, 'middle_line': 99.783775,
        'atr': 3.04598, 'upper_line': 105.875734, 'lower_line': 93.691816
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 80, 'middle_price': 104.871328, 'middle_line': 101.915361,
        'atr': 2.951128, 'upper_line': 107.817617, 'lower_line': 96.013105
    }
    
    # 获取实际记录
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None
    
    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")
    
    # 验证bar数量
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"
    
    # 验证第一条和最后一条记录的指标值
    if first_valid:
        assert abs(first_valid['middle_line'] - EXPECTED_FIRST_RECORD['middle_line']) < 1e-4, \
            f"First middle_line mismatch: expected {EXPECTED_FIRST_RECORD['middle_line']}, got {first_valid['middle_line']}"
        assert abs(first_valid['upper_line'] - EXPECTED_FIRST_RECORD['upper_line']) < 1e-4, \
            f"First upper_line mismatch: expected {EXPECTED_FIRST_RECORD['upper_line']}, got {first_valid['upper_line']}"
        assert abs(first_valid['lower_line'] - EXPECTED_FIRST_RECORD['lower_line']) < 1e-4, \
            f"First lower_line mismatch: expected {EXPECTED_FIRST_RECORD['lower_line']}, got {first_valid['lower_line']}"
    
    if last_valid:
        assert abs(last_valid['middle_line'] - EXPECTED_LAST_RECORD['middle_line']) < 1e-4, \
            f"Last middle_line mismatch: expected {EXPECTED_LAST_RECORD['middle_line']}, got {last_valid['middle_line']}"
        assert abs(last_valid['upper_line'] - EXPECTED_LAST_RECORD['upper_line']) < 1e-4, \
            f"Last upper_line mismatch: expected {EXPECTED_LAST_RECORD['upper_line']}, got {last_valid['upper_line']}"
        assert abs(last_valid['lower_line'] - EXPECTED_LAST_RECORD['lower_line']) < 1e-4, \
            f"Last lower_line mismatch: expected {EXPECTED_LAST_RECORD['lower_line']}, got {last_valid['lower_line']}"


def test_timeline_sma_line_operations():
    """测试 TimeLine + SMA 指标"""
    strategy = run_strategy(TimeLineSmaTestStrategy, num_bars=100, seed=42)
    
    # 验证bar数量 (由于指标warmup期，实际进入next的bar数量会少于100)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")
    
    # 验证有记录的值
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"
    
    # 预期值 (从master版本获取)
    EXPECTED_BAR_NUM = 81
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'close': 100.964345, 'day_avg_price': 99.517016, 'ma_value': 99.517016
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 81, 'close': 104.674652, 'day_avg_price': 100.662885, 'ma_value': 101.992377
    }
    
    # 获取实际记录
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None
    
    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")
    
    # 验证bar数量
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"
    
    # 验证第一条和最后一条记录
    if first_valid:
        assert abs(first_valid['day_avg_price'] - EXPECTED_FIRST_RECORD['day_avg_price']) < 1e-4, \
            f"First day_avg_price mismatch: expected {EXPECTED_FIRST_RECORD['day_avg_price']}, got {first_valid['day_avg_price']}"
        assert abs(first_valid['ma_value'] - EXPECTED_FIRST_RECORD['ma_value']) < 1e-4, \
            f"First ma_value mismatch: expected {EXPECTED_FIRST_RECORD['ma_value']}, got {first_valid['ma_value']}"
    
    if last_valid:
        assert abs(last_valid['day_avg_price'] - EXPECTED_LAST_RECORD['day_avg_price']) < 1e-4, \
            f"Last day_avg_price mismatch: expected {EXPECTED_LAST_RECORD['day_avg_price']}, got {last_valid['day_avg_price']}"
        assert abs(last_valid['ma_value'] - EXPECTED_LAST_RECORD['ma_value']) < 1e-4, \
            f"Last ma_value mismatch: expected {EXPECTED_LAST_RECORD['ma_value']}, got {last_valid['ma_value']}"


def test_highest_lowest_line_operations():
    """测试 Highest/Lowest 指标"""
    strategy = run_strategy(HighestLowestTestStrategy, num_bars=100, seed=42)
    
    # 验证bar数量 (由于指标warmup期，实际进入next的bar数量会少于100)
    assert strategy.bar_num > 0, f"Expected positive bar count, got {strategy.bar_num}"
    print(f"Total bars processed in next(): {strategy.bar_num}")
    
    # 验证有记录的值
    assert len(strategy.recorded_values) > 0, "No valid indicator values recorded"
    
    # 预期值 (从master版本获取)
    EXPECTED_BAR_NUM = 81
    EXPECTED_FIRST_RECORD = {
        'bar_num': 1, 'high': 102.885526, 'low': 100.605869, 
        'highest_high': 102.885526, 'lowest_low': 95.794978
    }
    EXPECTED_LAST_RECORD = {
        'bar_num': 81, 'high': 106.508498, 'low': 103.430834,
        'highest_high': 106.609724, 'lowest_low': 95.691099
    }
    
    # 获取实际记录
    first_valid = strategy.recorded_values[0] if strategy.recorded_values else None
    last_valid = strategy.recorded_values[-1] if strategy.recorded_values else None
    
    print(f"First valid record: {first_valid}")
    print(f"Last valid record: {last_valid}")
    print(f"Total valid records: {len(strategy.recorded_values)}")
    
    # 验证bar数量
    assert strategy.bar_num == EXPECTED_BAR_NUM, \
        f"Bar count mismatch: expected {EXPECTED_BAR_NUM}, got {strategy.bar_num}"
    
    # 验证第一条和最后一条记录
    if first_valid:
        assert abs(first_valid['highest_high'] - EXPECTED_FIRST_RECORD['highest_high']) < 1e-4, \
            f"First highest_high mismatch: expected {EXPECTED_FIRST_RECORD['highest_high']}, got {first_valid['highest_high']}"
        assert abs(first_valid['lowest_low'] - EXPECTED_FIRST_RECORD['lowest_low']) < 1e-4, \
            f"First lowest_low mismatch: expected {EXPECTED_FIRST_RECORD['lowest_low']}, got {first_valid['lowest_low']}"
    
    if last_valid:
        assert abs(last_valid['highest_high'] - EXPECTED_LAST_RECORD['highest_high']) < 1e-4, \
            f"Last highest_high mismatch: expected {EXPECTED_LAST_RECORD['highest_high']}, got {last_valid['highest_high']}"
        assert abs(last_valid['lowest_low'] - EXPECTED_LAST_RECORD['lowest_low']) < 1e-4, \
            f"Last lowest_low mismatch: expected {EXPECTED_LAST_RECORD['lowest_low']}, got {last_valid['lowest_low']}"


def collect_baseline_values():
    """收集基准值 - 在master分支运行此函数获取预期值
    
    使用方法:
    1. 切换到 master 分支: git checkout master
    2. 安装 master 版本: pip install -U .
    3. 运行: python tests/add_tests/test_line_operations.py --collect-baseline
    4. 复制输出的值到对应的测试函数中
    """
    print("=" * 80)
    print("COLLECTING BASELINE VALUES FROM MASTER BRANCH")
    print("=" * 80)
    
    # MACD EMA Test
    print("\n### MACD EMA Test ###")
    strategy = run_strategy(MacdEmaTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    # Keltner Test
    print("\n### Keltner Channel Test ###")
    strategy = run_strategy(KeltnerTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    # TimeLine SMA Test
    print("\n### TimeLine + SMA Test ###")
    strategy = run_strategy(TimeLineSmaTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    # Highest/Lowest Test
    print("\n### Highest/Lowest Test ###")
    strategy = run_strategy(HighestLowestTestStrategy, num_bars=100, seed=42)
    print(f"EXPECTED_BAR_NUM = {strategy.bar_num}")
    if strategy.recorded_values:
        first = strategy.recorded_values[0]
        last = strategy.recorded_values[-1]
        print(f"EXPECTED_FIRST_RECORD = {first}")
        print(f"EXPECTED_LAST_RECORD = {last}")
    
    print("\n" + "=" * 80)
    print("Baseline collection complete. Copy these values to the test functions.")
    print("=" * 80)


def test_run():
    """pytest入口 - 运行所有line操作测试"""
    test_macd_ema_line_operations()
    test_keltner_line_operations()
    test_timeline_sma_line_operations()
    test_highest_lowest_line_operations()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--collect-baseline':
        collect_baseline_values()
        sys.exit(0)
    
    print("=" * 60)
    print("Running MACD EMA Line Operations Test")
    print("=" * 60)
    test_macd_ema_line_operations()
    
    print("\n" + "=" * 60)
    print("Running Keltner Channel Line Operations Test")
    print("=" * 60)
    test_keltner_line_operations()
    
    print("\n" + "=" * 60)
    print("Running TimeLine + SMA Line Operations Test")
    print("=" * 60)
    test_timeline_sma_line_operations()
    
    print("\n" + "=" * 60)
    print("Running Highest/Lowest Line Operations Test")
    print("=" * 60)
    test_highest_lowest_line_operations()
    
    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)

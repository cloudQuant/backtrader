#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""布林带突破策略参数优化脚本.

使用本地 Binance 历史数据进行参数优化，找出最优的布林带参数组合。

数据来源: Binance 公开数据 (ZIP/CSV 格式)
策略: 布林带突破 + ATR 动态止损

优化参数:
- period: 布林带周期 (10-100)
- devfactor: 标准差倍数 (1.5-3.0)
- atr_period: ATR周期 (7-21)
- atr_mult: ATR止损倍数 (1.0-3.0)

用法:
    python examples/optimize_bollinger_strategy.py --data-dir /path/to/data
    python examples/optimize_bollinger_strategy.py --data-dir "J:/binance-public-data/data/futures/um/monthly/klines/MINAUSDT/15m" --start-date 2024-01-01 --end-date 2024-12-31
"""

import os
import sys
import zipfile
import io
import argparse
from datetime import datetime
from pathlib import Path
from multiprocessing import Pool, cpu_count
from functools import partial

import pandas as pd
import backtrader as bt


# =============================================================================
# 数据加载器 - 加载 Binance ZIP/CSV 数据
# =============================================================================

class BinanceZipCSVData(bt.feeds.PandasData):
    """Binance ZIP/CSV 数据加载器.
    
    Binance 数据格式:
    open_time, open, high, low, close, volume, close_time, 
    quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore
    """
    
    # 使用列索引而不是列名 (-1 表示不使用该列)
    params = (
        ('datetime', None),  # 使用 DataFrame 索引作为日期时间
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),
    )


def load_binance_data(data_dir: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """加载 Binance ZIP/CSV 数据.
    
    Args:
        data_dir: 数据目录路径，包含 ZIP 文件
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
    
    Returns:
        合并后的 DataFrame
    """
    data_path = Path(data_dir)
    all_data = []
    
    # 获取所有 ZIP 文件并排序
    zip_files = sorted(data_path.glob('*.zip'))
    
    if not zip_files:
        raise FileNotFoundError(f"No ZIP files found in {data_dir}")
    
    print(f"找到 {len(zip_files)} 个数据文件")
    
    for zip_file in zip_files:
        try:
            with zipfile.ZipFile(zip_file, 'r') as z:
                # 获取 ZIP 内的 CSV 文件
                csv_files = [f for f in z.namelist() if f.endswith('.csv')]
                if not csv_files:
                    continue
                
                # 读取 CSV
                with z.open(csv_files[0]) as f:
                    df = pd.read_csv(f)
                    all_data.append(df)
                    
        except Exception as e:
            print(f"警告: 无法读取 {zip_file}: {e}")
            continue
    
    if not all_data:
        raise ValueError("No data loaded from ZIP files")
    
    # 合并所有数据
    combined = pd.concat(all_data, ignore_index=True)
    
    # 转换时间戳
    combined['datetime'] = pd.to_datetime(combined['open_time'], unit='ms')
    
    # 确保数值类型
    for col in ['open', 'high', 'low', 'close', 'volume']:
        combined[col] = pd.to_numeric(combined[col], errors='coerce')
    
    # 按时间排序并去重
    combined = combined.sort_values('datetime').drop_duplicates(subset=['datetime'])
    
    # 日期过滤
    if start_date:
        combined = combined[combined['datetime'] >= start_date]
    if end_date:
        combined = combined[combined['datetime'] <= end_date]
    
    # 设置索引
    combined = combined.set_index('datetime')
    
    print(f"数据加载完成: {len(combined)} 条记录")
    print(f"时间范围: {combined.index.min()} 至 {combined.index.max()}")
    
    return combined


# =============================================================================
# 布林带突破策略 (回测版)
# =============================================================================

class BollingerBandsStrategy(bt.Strategy):
    """布林带突破策略 (支持做多做空).
    
    交易逻辑:
    - 突破上轨 → 开多仓
    - 跌破中轨 → 平多仓
    - 跌破下轨 → 开空仓
    - 突破中轨 → 平空仓
    - ATR 动态止损
    """
    
    params = (
        ('period', 60),           # 布林带周期
        ('devfactor', 2.0),       # 标准差倍数
        ('atr_period', 14),       # ATR周期
        ('atr_mult', 2.0),        # ATR止损倍数
        ('order_pct', 0.95),      # 每次下单使用资金比例
        ('use_stop_loss', True),  # 是否启用止损
        ('printlog', False),      # 是否打印日志
    )
    
    def __init__(self):
        # 布林带指标
        self.bollinger = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )
        
        # ATR 指标
        self.atr = bt.indicators.ATR(
            self.data,
            period=self.p.atr_period
        )
        
        # 布林带各轨道
        self.mid = self.bollinger.mid
        self.top = self.bollinger.top
        self.bot = self.bollinger.bot
        
        # 交易状态
        self.order = None
        self.long_stop_price = None
        self.short_stop_price = None
        self.entry_price = None
        
        # 统计
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
    
    def log(self, txt, dt=None):
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY @ {order.executed.price:.6f}, Size: {order.executed.size}')
            else:
                self.log(f'SELL @ {order.executed.price:.6f}, Size: {order.executed.size}')
        
        self.order = None
    
    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_count += 1
            if trade.pnl > 0:
                self.win_count += 1
            else:
                self.loss_count += 1
            self.log(f'TRADE PNL: Gross={trade.pnl:.4f}, Net={trade.pnlcomm:.4f}')
    
    def next(self):
        # 等待订单完成
        if self.order:
            return
        
        # 确保有足够数据
        if len(self.data) < self.p.period + 1:
            return
        
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        middle_band = self.mid[0]
        atr_value = self.atr[0]
        
        # 检查指标有效性
        if any(x is None or x != x for x in [current_price, upper_band, lower_band, middle_band, atr_value]):
            return
        
        position_size = self.position.size
        
        # 计算下单数量
        if position_size == 0:
            cash = self.broker.getcash()
            size = int((cash * self.p.order_pct) / current_price)
            if size <= 0:
                return
        else:
            size = abs(position_size)
        
        # === 止损检查 ===
        if self.p.use_stop_loss:
            # 多仓止损
            if position_size > 0 and self.long_stop_price:
                if current_price <= self.long_stop_price:
                    self.log(f'LONG STOP LOSS @ {current_price:.6f}')
                    self.order = self.sell(size=position_size)
                    self.long_stop_price = None
                    self.entry_price = None
                    return
            
            # 空仓止损
            elif position_size < 0 and self.short_stop_price:
                if current_price >= self.short_stop_price:
                    self.log(f'SHORT STOP LOSS @ {current_price:.6f}')
                    self.order = self.buy(size=abs(position_size))
                    self.short_stop_price = None
                    self.entry_price = None
                    return
        
        # === 开仓逻辑 ===
        if position_size == 0:
            # 突破上轨 → 开多
            if current_price > upper_band:
                self.log(f'LONG ENTRY: price={current_price:.6f} > upper={upper_band:.6f}')
                self.order = self.buy(size=size)
                self.entry_price = current_price
                self.long_stop_price = current_price - (atr_value * self.p.atr_mult)
                return
            
            # 跌破下轨 → 开空
            elif current_price < lower_band:
                self.log(f'SHORT ENTRY: price={current_price:.6f} < lower={lower_band:.6f}')
                self.order = self.sell(size=size)
                self.entry_price = current_price
                self.short_stop_price = current_price + (atr_value * self.p.atr_mult)
                return
        
        # === 平仓逻辑 ===
        elif position_size > 0:
            # 跌破中轨 → 平多
            if current_price < middle_band:
                self.log(f'LONG EXIT: price={current_price:.6f} < mid={middle_band:.6f}')
                self.order = self.sell(size=position_size)
                self.long_stop_price = None
                self.entry_price = None
                return
        
        elif position_size < 0:
            # 突破中轨 → 平空
            if current_price > middle_band:
                self.log(f'SHORT EXIT: price={current_price:.6f} > mid={middle_band:.6f}')
                self.order = self.buy(size=abs(position_size))
                self.short_stop_price = None
                self.entry_price = None
                return
    
    def stop(self):
        """策略结束时输出统计"""
        win_rate = self.win_count / self.trade_count * 100 if self.trade_count > 0 else 0
        self.log(f'Period={self.p.period}, Dev={self.p.devfactor:.1f}, '
                f'ATR_P={self.p.atr_period}, ATR_M={self.p.atr_mult:.1f}, '
                f'Trades={self.trade_count}, WinRate={win_rate:.1f}%, '
                f'Final={self.broker.getvalue():.2f}', dt=self.datas[0].datetime.date(0))




# =============================================================================
# 主函数
# =============================================================================

def run_single_backtest(data_df, params):
    """运行单次回测"""
    cerebro = bt.Cerebro()

    # 添加数据
    data = BinanceZipCSVData(dataname=data_df)
    cerebro.adddata(data)

    # 添加策略
    cerebro.addstrategy(
        BollingerBandsStrategy,
        period=params['period'],
        devfactor=params['devfactor'],
        atr_period=params['atr_period'],
        atr_mult=params['atr_mult'],
        printlog=False
    )

    # 设置初始资金和手续费
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.0004)  # 0.04% 手续费

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # 运行回测
    results = cerebro.run()
    strat = results[0]

    # 收集结果
    final_value = cerebro.broker.getvalue()
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    # 提取交易统计
    total_trades = trades.get('total', {}).get('closed', 0)
    won = trades.get('won', {}).get('total', 0)
    win_rate = won / total_trades * 100 if total_trades > 0 else 0

    return {
        'params': params,
        'final_value': final_value,
        'return_pct': (final_value - 10000) / 10000 * 100,
        'sharpe_ratio': sharpe.get('sharperatio', 0) or 0,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0) or 0,
        'total_trades': total_trades,
        'win_rate': win_rate,
    }


def run_backtest_with_dict(params, data_dict):
    """从字典格式的数据运行单次回测 (用于多进程).

    Args:
        params: 策略参数字典
        data_dict: 数据字典 (dates, open, high, low, close, volume)

    Returns:
        回测结果字典
    """
    try:
        # 将字典转换回 DataFrame
        import pandas as pd
        data_df = pd.DataFrame({
            'open': data_dict['open'],
            'high': data_dict['high'],
            'low': data_dict['low'],
            'close': data_dict['close'],
            'volume': data_dict['volume'],
        })
        data_df.index = pd.to_datetime(data_dict['dates'], unit='ms')

        return run_single_backtest(data_df, params)
    except Exception as e:
        print(f"回测失败: {params}, 错误: {e}")
        return None


def _print_result_inline(current: int, total: int, result: dict):
    """打印单次回测结果 (单行格式).

    Args:
        current: 当前完成的数量
        total: 总数量
        result: 回测结果字典
    """
    p = result['params']
    ret = result['return_pct']
    sharpe = result['sharpe_ratio']
    dd = result['max_drawdown']
    trades = result['total_trades']
    win_rate = result['win_rate']

    # 格式化输出
    print(f"[{current}/{total}] "
          f"P={p['period']:3d} D={p['devfactor']:.1f} "
          f"ATR_P={p['atr_period']:2d} ATR_M={p['atr_mult']:.1f} | "
          f"收益: {ret:6.2f}% | "
          f"夏普: {sharpe:5.2f} | "
          f"回撤: {dd:5.2f}% | "
          f"交易: {trades:3d} | "
          f"胜率: {win_rate:5.1f}%")


def run_optimization(data_dir: str,
                     start_date: str = None,
                     end_date: str = None,
                     use_multiprocessing: bool = True,
                     cpu_usage: float = 0.8):
    """运行参数优化.

    Args:
        data_dir: 数据目录
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        use_multiprocessing: 是否使用多进程
        cpu_usage: CPU 使用比例 (0.1-1.0), 默认 0.8 (80%)
    """
    print("=" * 70)
    print("布林带策略参数优化")
    print("=" * 70)

    # 加载数据
    print("\n[1] 加载数据...")
    data_df = load_binance_data(data_dir, start_date, end_date)

    # 将数据转换为可序列化的格式 (用于多进程)
    # 将 DataFrame 转换为 dict 格式，这样可以通过 pickle 传递
    data_dict = {
        'dates': data_df.index.astype('int64').tolist(),  # 转换为 unix 时间戳
        'open': data_df['open'].tolist(),
        'high': data_df['high'].tolist(),
        'low': data_df['low'].tolist(),
        'close': data_df['close'].tolist(),
        'volume': data_df['volume'].tolist(),
    }

    # 定义参数空间
    print("\n[2] 定义参数空间...")
    param_space = []

    # 参数范围
    periods = [20, 30, 40, 50, 60, 80, 100]
    devfactors = [1.5, 2.0, 2.5, 3.0]
    atr_periods = [7, 10, 14, 20]
    atr_mults = [1.0, 1.5, 2.0, 2.5, 3.0]

    for period in periods:
        for devfactor in devfactors:
            for atr_period in atr_periods:
                for atr_mult in atr_mults:
                    param_space.append({
                        'period': period,
                        'devfactor': devfactor,
                        'atr_period': atr_period,
                        'atr_mult': atr_mult,
                    })

    total_combinations = len(param_space)
    print(f"参数组合总数: {total_combinations}")

    # 计算 CPU 核心数
    total_cores = cpu_count()
    n_workers = max(1, int(total_cores * cpu_usage))
    print(f"检测到 {total_cores} 个 CPU 核心，使用 {n_workers} 个 ({cpu_usage*100:.0f}%)")

    # 运行优化
    print("\n[3] 运行优化...")

    if use_multiprocessing and total_combinations > 10 and n_workers > 1:
        # 多进程优化
        print(f"使用多进程并行计算...")

        # 创建包装函数，固定 data_dict 参数
        worker_func = partial(run_backtest_with_dict, data_dict=data_dict)

        with Pool(processes=n_workers) as pool:
            # 使用 imap_unordered 获取进度
            results = []
            completed = 0
            for result in pool.imap_unordered(worker_func, param_space):
                completed += 1
                if result is not None:
                    results.append(result)
                    # 实时显示结果
                    _print_result_inline(completed, total_combinations, result)
                else:
                    print(f"[{completed}/{total_combinations}] 回测失败")

    else:
        # 单进程优化
        print("使用单进程计算...")
        results = []
        for i, params in enumerate(param_space):
            try:
                result = run_single_backtest(data_df, params)
                results.append(result)
                # 实时显示结果
                _print_result_inline(i + 1, total_combinations, result)
            except Exception as e:
                print(f"[{i + 1}/{total_combinations}] 参数组合失败: {params}, 错误: {e}")
    
    # 分析结果
    print("\n[4] 分析结果...")
    
    if not results:
        print("没有有效的回测结果!")
        return
    
    # 按收益率排序
    results_sorted = sorted(results, key=lambda x: x['return_pct'], reverse=True)
    
    # 输出 Top 20 结果
    print("\n" + "=" * 100)
    print("Top 20 参数组合 (按收益率排序)")
    print("=" * 100)
    print(f"{'Rank':<5} {'Period':<8} {'DevFactor':<10} {'ATR_P':<8} {'ATR_M':<8} "
          f"{'Return%':<10} {'Sharpe':<8} {'MaxDD%':<10} {'Trades':<8} {'WinRate%':<10}")
    print("-" * 100)
    
    for i, r in enumerate(results_sorted[:20], 1):
        p = r['params']
        print(f"{i:<5} {p['period']:<8} {p['devfactor']:<10.1f} {p['atr_period']:<8} {p['atr_mult']:<8.1f} "
              f"{r['return_pct']:<10.2f} {r['sharpe_ratio']:<8.2f} {r['max_drawdown']:<10.2f} "
              f"{r['total_trades']:<8} {r['win_rate']:<10.1f}")
    
    # 输出最佳参数
    best = results_sorted[0]
    print("\n" + "=" * 70)
    print("最佳参数组合")
    print("=" * 70)
    print(f"布林带周期 (period):     {best['params']['period']}")
    print(f"标准差倍数 (devfactor):  {best['params']['devfactor']}")
    print(f"ATR周期 (atr_period):    {best['params']['atr_period']}")
    print(f"ATR止损倍数 (atr_mult):  {best['params']['atr_mult']}")
    print("-" * 70)
    print(f"最终资金:    ${best['final_value']:.2f}")
    print(f"总收益率:    {best['return_pct']:.2f}%")
    print(f"夏普比率:    {best['sharpe_ratio']:.2f}")
    print(f"最大回撤:    {best['max_drawdown']:.2f}%")
    print(f"交易次数:    {best['total_trades']}")
    print(f"胜率:        {best['win_rate']:.1f}%")
    print("=" * 70)
    
    # 保存结果到 CSV
    output_file = Path(data_dir).parent / 'optimization_results.csv'
    df_results = pd.DataFrame([
        {
            'period': r['params']['period'],
            'devfactor': r['params']['devfactor'],
            'atr_period': r['params']['atr_period'],
            'atr_mult': r['params']['atr_mult'],
            'return_pct': r['return_pct'],
            'sharpe_ratio': r['sharpe_ratio'],
            'max_drawdown': r['max_drawdown'],
            'total_trades': r['total_trades'],
            'win_rate': r['win_rate'],
            'final_value': r['final_value'],
        }
        for r in results_sorted
    ])
    df_results.to_csv(output_file, index=False)
    print(f"\n结果已保存到: {output_file}")
    
    return results_sorted


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='布林带策略参数优化',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
    # 使用默认参数 (80%% CPU)
    python %(prog)s --data-dir /path/to/data

    # 指定日期范围
    python %(prog)s --data-dir /path/to/data --start-date 2024-01-01 --end-date 2024-12-31

    # 使用 50%% CPU
    python %(prog)s --data-dir /path/to/data --cpu-usage 0.5

    # 禁用多进程
    python %(prog)s --data-dir /path/to/data --no-multiprocessing
        '''
    )

    parser.add_argument(
        '--data-dir',
        type=str,
        required=True,
        help='Binance 数据目录路径 (包含 ZIP 文件)'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        default=None,
        help='起始日期 (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='结束日期 (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--cpu-usage',
        type=float,
        default=0.8,
        help='CPU 使用比例 (0.1-1.0), 默认 0.8 (80%%)'
    )
    parser.add_argument(
        '--no-multiprocessing',
        action='store_true',
        help='禁用多进程'
    )

    args = parser.parse_args()

    # 验证 CPU usage 参数
    if not 0.1 <= args.cpu_usage <= 1.0:
        parser.error('--cpu-usage 必须在 0.1 到 1.0 之间')

    # 运行优化
    run_optimization(
        data_dir=args.data_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        use_multiprocessing=not args.no_multiprocessing,
        cpu_usage=args.cpu_usage
    )

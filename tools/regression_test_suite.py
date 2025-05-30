#!/usr/bin/env python3
"""
Backtrader Functional Regression Test Suite

功能回归测试套件，用于确保在去除元编程过程中核心功能不会被破坏。
"""

import os
import sys
import unittest
import tempfile
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt
import pandas as pd
import numpy as np


class RegressionTestSuite(unittest.TestCase):
    """回归测试套件"""
    
    def setUp(self):
        """测试准备"""
        # 生成一致的测试数据
        np.random.seed(42)
        dates = pd.date_range('2020-01-01', periods=100, freq='D')
        close = 100 + np.cumsum(np.random.randn(100) * 0.02)
        high = close + np.random.uniform(0, 2, 100)
        low = close - np.random.uniform(0, 2, 100)
        open_ = close + np.random.uniform(-1, 1, 100)
        volume = np.random.randint(1000, 10000, 100)
        
        # 创建DataFrame，使用dates作为index（这是PandasData期望的格式）
        self.test_data = pd.DataFrame({
            'open': open_,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        }, index=dates)
    
    def test_cerebro_basic_functionality(self):
        """测试Cerebro基础功能"""
        cerebro = bt.Cerebro()
        
        # 检查Cerebro创建
        self.assertIsInstance(cerebro, bt.Cerebro)
        
        # 添加数据
        data = bt.feeds.PandasData(dataname=self.test_data)
        cerebro.adddata(data)
        
        # 添加策略
        cerebro.addstrategy(SimpleTestStrategy)
        
        # 设置初始资金
        cerebro.broker.setcash(10000.0)
        initial_cash = cerebro.broker.getvalue()
        
        # 运行
        results = cerebro.run()
        
        # 验证结果
        self.assertIsNotNone(results)
        self.assertEqual(len(results), 1)
        final_value = cerebro.broker.getvalue()
        self.assertIsInstance(final_value, (int, float))
        
        print(f"初始资金: {initial_cash}, 最终价值: {final_value}")
    
    def test_indicators_functionality(self):
        """测试指标功能"""
        cerebro = bt.Cerebro()
        data = bt.feeds.PandasData(dataname=self.test_data)
        cerebro.adddata(data)
        cerebro.addstrategy(IndicatorTestStrategy)
        
        results = cerebro.run()
        strategy = results[0]
        
        # 验证指标存在且计算正确
        self.assertTrue(hasattr(strategy, 'sma'))
        self.assertTrue(hasattr(strategy, 'rsi'))
        self.assertTrue(hasattr(strategy, 'macd'))
        
        # 验证指标值
        self.assertIsNotNone(strategy.sma[0])
        self.assertIsNotNone(strategy.rsi[0])
        
        print(f"SMA值: {strategy.sma[0]}, RSI值: {strategy.rsi[0]}")
    
    def test_parameter_system(self):
        """测试参数系统"""
        # 测试默认参数
        strategy = ParameterTestStrategy()
        self.assertEqual(strategy.params.period, 15)
        self.assertEqual(strategy.params.threshold, 0.02)
        
        # 测试参数访问的多种方式
        self.assertEqual(strategy.p.period, 15)
        self.assertEqual(strategy.params.period, strategy.p.period)
        
        print(f"参数测试通过: period={strategy.params.period}, threshold={strategy.params.threshold}")
    
    def test_data_feed_access(self):
        """测试数据源访问"""
        data = bt.feeds.PandasData(dataname=self.test_data)
        
        # 创建一个简单的cerebro来初始化数据
        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(DataAccessTestStrategy)
        
        results = cerebro.run()
        strategy = results[0]
        
        # 验证数据访问
        self.assertTrue(hasattr(strategy, 'data_values'))
        self.assertGreater(len(strategy.data_values), 0)
        
        print(f"数据访问测试通过: 获取了 {len(strategy.data_values)} 个数据点")
    
    def test_analyzer_functionality(self):
        """测试分析器功能"""
        cerebro = bt.Cerebro()
        data = bt.feeds.PandasData(dataname=self.test_data)
        cerebro.adddata(data)
        cerebro.addstrategy(SimpleTestStrategy)
        
        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        
        results = cerebro.run()
        strategy = results[0]
        
        # 验证分析器存在
        self.assertTrue(hasattr(strategy, 'analyzers'))
        self.assertIn('sharpe', strategy.analyzers.getnames())
        self.assertIn('returns', strategy.analyzers.getnames())
        self.assertIn('drawdown', strategy.analyzers.getnames())
        
        # 获取分析结果
        sharpe_ratio = strategy.analyzers.sharpe.get_analysis()
        returns = strategy.analyzers.returns.get_analysis()
        drawdown = strategy.analyzers.drawdown.get_analysis()
        
        print(f"分析器测试通过 - Sharpe: {sharpe_ratio}, Returns: {returns}")
    
    def test_broker_functionality(self):
        """测试经纪人功能"""
        cerebro = bt.Cerebro()
        data = bt.feeds.PandasData(dataname=self.test_data)
        cerebro.adddata(data)
        cerebro.addstrategy(BrokerTestStrategy)
        
        # 设置经纪人参数
        cerebro.broker.setcash(10000.0)
        cerebro.broker.setcommission(commission=0.001)
        
        initial_cash = cerebro.broker.getvalue()
        results = cerebro.run()
        final_value = cerebro.broker.getvalue()
        
        strategy = results[0]
        
        # 验证交易记录
        self.assertTrue(hasattr(strategy, 'order_count'))
        self.assertGreaterEqual(strategy.order_count, 0)
        
        print(f"经纪人测试通过 - 初始: {initial_cash}, 最终: {final_value}, 订单数: {strategy.order_count}")
    
    def test_sizer_functionality(self):
        """测试仓位大小管理器功能"""
        cerebro = bt.Cerebro()
        data = bt.feeds.PandasData(dataname=self.test_data)
        cerebro.adddata(data)
        cerebro.addstrategy(SimpleTestStrategy)
        
        # 添加仓位管理器
        cerebro.addsizer(bt.sizers.FixedSize, stake=10)
        
        results = cerebro.run()
        self.assertIsNotNone(results)
        
        print("仓位管理器测试通过")
    
    def test_observer_functionality(self):
        """测试观察者功能"""
        cerebro = bt.Cerebro()
        data = bt.feeds.PandasData(dataname=self.test_data)
        cerebro.adddata(data)
        cerebro.addstrategy(SimpleTestStrategy)
        
        # 添加观察者
        cerebro.addobserver(bt.observers.Broker)
        cerebro.addobserver(bt.observers.Trades)
        
        results = cerebro.run()
        self.assertIsNotNone(results)
        
        print("观察者测试通过")
    
    def test_metaclass_dependent_features(self):
        """测试依赖元类的功能（用于验证去除元编程后的兼容性）"""
        # 测试Lines系统
        try:
            class TestIndicator(bt.Indicator):
                lines = ('test_line',)
                
                def __init__(self):
                    self.lines.test_line = self.data.close
            
            cerebro = bt.Cerebro()
            data = bt.feeds.PandasData(dataname=self.test_data)
            cerebro.adddata(data)
            
            class TestStrategy(bt.Strategy):
                def __init__(self):
                    self.test_ind = TestIndicator(self.data)
            
            cerebro.addstrategy(TestStrategy)
            results = cerebro.run()
            
            print("元类依赖功能测试通过")
            
        except Exception as e:
            self.fail(f"元类依赖功能测试失败: {e}")


class SimpleTestStrategy(bt.Strategy):
    """简单测试策略"""
    
    def __init__(self):
        self.sma = bt.indicators.SimpleMovingAverage(self.data.close, period=15)
        self.order_count = 0
    
    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy()
                self.order_count += 1
        else:
            if self.data.close[0] < self.sma[0]:
                self.sell()
                self.order_count += 1


class IndicatorTestStrategy(bt.Strategy):
    """指标测试策略"""
    
    def __init__(self):
        self.sma = bt.indicators.SimpleMovingAverage(self.data.close, period=15)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.macd = bt.indicators.MACD(self.data.close)
        self.bb = bt.indicators.BollingerBands(self.data.close)


class ParameterTestStrategy(bt.Strategy):
    """参数测试策略"""
    
    params = (
        ('period', 15),
        ('threshold', 0.02),
    )


class DataAccessTestStrategy(bt.Strategy):
    """数据访问测试策略"""
    
    def __init__(self):
        self.data_values = []
    
    def next(self):
        self.data_values.append({
            'open': self.data.open[0],
            'high': self.data.high[0],
            'low': self.data.low[0],
            'close': self.data.close[0],
            'volume': self.data.volume[0]
        })


class BrokerTestStrategy(bt.Strategy):
    """经纪人测试策略"""
    
    def __init__(self):
        self.sma = bt.indicators.SimpleMovingAverage(self.data.close, period=10)
        self.order_count = 0
    
    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy(size=10)
                self.order_count += 1
        else:
            if self.data.close[0] < self.sma[0]:
                self.sell(size=10)
                self.order_count += 1


class RegressionTestRunner:
    """回归测试运行器"""
    
    def __init__(self):
        self.results = {}
    
    def run_all_tests(self):
        """运行所有回归测试"""
        print("="*60)
        print("Backtrader Functional Regression Test Suite")
        print("="*60)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-"*60)
        
        # 创建测试套件
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(RegressionTestSuite)
        
        # 运行测试
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        # 记录结果
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'tests_run': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'success': result.wasSuccessful(),
            'failure_details': [str(f) for f in result.failures],
            'error_details': [str(e) for e in result.errors]
        }
        
        print("-"*60)
        print(f"测试完成: {result.testsRun} 个测试")
        print(f"成功: {result.wasSuccessful()}")
        print(f"失败: {len(result.failures)}")
        print(f"错误: {len(result.errors)}")
        
        self.save_results()
        return result.wasSuccessful()
    
    def save_results(self):
        """保存测试结果"""
        os.makedirs('test_results', exist_ok=True)
        filename = f"test_results/regression_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        print(f"测试结果已保存到: {filename}")


if __name__ == '__main__':
    runner = RegressionTestRunner()
    success = runner.run_all_tests()
    sys.exit(0 if success else 1) 
### 背景

现在有一些测试用例失败了，需要修复源代码中的bug，确保所有的测试用例都能通过。

### 任务

1. 修复失败的测试用例
2. 确保所有的测试用例都能通过
3. 只能修改源代码，不能修改测试用例。
4. 每次修改过源代码之后，需要pip install -U .   重新安装一下，使得源代码生效
5. 测试用例一定不能修改，这些测试用例都是在正常条件下能够通过的。
6. 需要确保所有的测试用例都能通过才算修复成功： pytest tests -n 8 所有的都通过，不允许有失败的测试用例。

### 现在失败的测试用例：
============================== short test summary info ===============================
FAILED tests/strategies/test_06_macd_ema_fase_strategy.py::test_macd_ema_strategy - AssertionError: Expected bar_num=28069, got 28087
FAILED tests/strategies/test_18_etf_rotation_strategy.py::test_etf_rotation_strategy - TypeError: Lines.reset() missing 1 required positional argument: 'self'
FAILED tests/strategies/test_19_index_future_momentum.py::test_treasury_futures_macd_strategy - TypeError: Lines.reset() missing 1 required positional argument: 'self'
FAILED tests/strategies/test_20_arbitrage_strategy.py::test_treasury_futures_spread_arbitrage_strategy - TypeError: Lines.reset() missing 1 required positional argument: 'self'
FAILED tests/strategies/test_12_abberation_strategy.py::test_abberation_strategy - AssertionError: Expected bar_num=170081, got 169683
FAILED tests/strategies/test_08_kelter_strategy.py::test_keltner_strategy - ValueError: ordinal must be >= 1
FAILED tests/strategies/test_07_macd_ema_true_strategy.py::test_macd_ema_true_strategy - ValueError: ordinal must be >= 1
FAILED tests/strategies/test_17_cb_monday_strategy.py::test_cb_friday_rotation_strategy - ValueError: ordinal must be >= 1
FAILED tests/strategies/test_15_fenshi_ma_strategy.py::test_timeline_ma_strategy - AssertionError: Expected buy_count=1453, got 45935
FAILED tests/strategies/test_13_fei_strategy.py::test_fei_strategy - AssertionError: Expected bar_num=170081, got 169683
FAILED tests/strategies/test_16_cb_strategy.py::test_cb_intraday_strategy - ValueError: ordinal must be >= 1
FAILED tests/strategies/test_09_dual_thrust_strategy.py::test_dual_thrust_strategy - AssertionError: Expected annual_return=-0.010692176446733459, got -0.010682086442...

Results (195.18s (0:03:15)):
     349 passed
      12 failed
         - tests/strategies/test_06_macd_ema_fase_strategy.py:163 test_macd_ema_strategy
         - tests/strategies/test_18_etf_rotation_strategy.py:215 test_etf_rotation_strategy
         - tests/strategies/test_19_index_future_momentum.py:236 test_treasury_futures_macd_strategy
         - tests/strategies/test_20_arbitrage_strategy.py:278 test_treasury_futures_spread_arbitrage_strategy
         - tests/strategies/test_12_abberation_strategy.py:170 test_abberation_strategy
         - tests/strategies/test_08_kelter_strategy.py:223 test_keltner_strategy
         - tests/strategies/test_07_macd_ema_true_strategy.py:227 test_macd_ema_true_strategy
         - tests/strategies/test_17_cb_monday_strategy.py:166 test_cb_friday_rotation_strategy
         - tests/strategies/test_15_fenshi_ma_strategy.py:237 test_timeline_ma_strategy
         - tests/strategies/test_13_fei_strategy.py:199 test_fei_strategy
         - tests/strategies/test_16_cb_strategy.py:222 test_cb_intraday_strategy
         - tests/strategies/test_09_dual_thrust_strategy.py:201 test_dual_thrust_strategy
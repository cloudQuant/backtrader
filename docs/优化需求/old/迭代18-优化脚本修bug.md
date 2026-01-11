### 背景

现在新增了15个策略，只有5个是通过的，还有10个没通过，重构后项目的源代码还是存在问题，需要进一步修复。

### 目标
0. 每次运行的时候先分析一下remove-metaprogramming分支上测试策略的代码是否和master一样，如果不一样，把master上的修改成和remove-metaprogramming分支一致。
1. 优化backtrader/run_test_with_log.py，支持传入需要测试的策略作为参数，支持传入参数决定是，每次运行的时候，可以先切换到master分支，pip install -U . 进行安装更新，然后运行这个测试，测试策略；测试完成之后，再切回到remove-metaprogramming分支，pip install -U . 进行安装，运行测试；还是只在remove-metaprogramming分支上运行，pip install -U . 然后运行测试，然后对比一下logs中这两个分支的结果有什么不同，推测现在remove-metaprogramming分支有什么bug.
2. 修复remove-metaprogramming分支的bug，如果没有为测试策略新增log输出，那么pip install -U . 进行重新安装, 然后进行测试，这次测试就只需要在remove-metaprogramming分支上运行就可以了，master分支上已经有相应的结果了。如果为测试策略新增了log输出，那么就需要为master版本上的策略也增加相应的log输出，保证两个版本的测试策略代码是一样的，这个时候就需要在两个分支上都重新运行一下，确保结果一致。
3. 修复好这个脚本之后，先运行一下test_18_etf_rotation_strategy.py这个策略验证一下效果,看是否能够先切换到master，运行这个策略，然后切换到remove-metaprogramming分支运行同样的策略，在logs中输出差异。
<!-- 3. 先修复一下 FAILED tests/strategies/test_18_etf_rotation_strategy.py::test_etf_rotation_strategy - AssertionError: Expected buy_count=266, got 184 -->
<!-- 4. 修复成功的标准：在不修改测试期望值、输入数据和策略逻辑的情况下，这个策略通过了，并且没有新增失败的测试用例。

5. 现有的失败测试用例有：
10 failed
         - tests/strategies/test_18_etf_rotation_strategy.py:215 test_etf_rotation_strategy
         - tests/strategies/test_19_index_future_momentum.py:236 test_treasury_futures_macd_strategy
         - tests/strategies/test_06_macd_ema_fase_strategy.py:163 test_macd_ema_strategy
         - tests/strategies/test_13_fei_strategy.py:199 test_fei_strategy
         - tests/strategies/test_08_kelter_strategy.py:223 test_keltner_strategy
         - tests/strategies/test_07_macd_ema_true_strategy.py:227 test_macd_ema_true_strategy
         - tests/strategies/test_12_abberation_strategy.py:170 test_abberation_strategy
         - tests/strategies/test_15_fenshi_ma_strategy.py:237 test_timeline_ma_strategy
         - tests/strategies/test_16_cb_strategy.py:222 test_cb_intraday_strategy
         - tests/strategies/test_09_dual_thrust_strategy.py:201 test_dual_thrust_strategy -->
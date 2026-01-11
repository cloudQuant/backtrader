### 背景
在迭代37中，修复crossover.py这个指标，修复了test_120这个测试用例，但是导致了：
FAILED tests/original_tests/test_strategy_optimized.py::test_run - AssertionError: assert ['14525.80', ...4763.90', ...] == ['10000.00', ...00...
FAILED tests/strategies/test_35_sma_cross_signal_strategy.py::test_sma_cross_signal_strategy - AssertionError: Expected buy_count=14, got 13
FAILED tests/strategies/test_48_strategy_selection.py::test_strategy_selection - AssertionError: Expected final_value=105258.30, got 105508.4

### 修复方法建议
1. backtrader/run_test_with_log.py 这个运行这个策略，然后对比master分支上的结果，看看origin分支上的结果究竟差在哪里，然后去定位。
2. 如果必要，可以修改测试用例，增加注释，然后方便在两个分支上进行对比。
3. 需要进一步优化crossover这个，需要确保test_120和tests/original_tests/test_strategy_optimized.py，test_35，test_48都能通过。

### 资源
1. 修改当前测试脚本，比如新增了debug信息之类的，可以用backtrader/sync_to_master.py同步到master分支上的对应脚本
2. 可以使用backtrader/run_test_with_log.py这个脚本，对比当前分支(origin)和master分支上运行这个策略的结果，形成日志，放到logs，方便后续对比差异。

### 限制

1. 不允许修改测试用例，尤其是测试用例的期望值,这些期望值都是master版本上验证正确的。
2. 修改过源代码重新测试的时候，最好pip install -U . 重新安装一下。
3. 现在版本的代码和原始的底层实现的逻辑已经有很大不一样了，每个函数的逻辑可能会存在不一样，不能按照master版本的相应函数来实现现在版本的函数。即不允许：restore the master branch's simpler, declarative implementation
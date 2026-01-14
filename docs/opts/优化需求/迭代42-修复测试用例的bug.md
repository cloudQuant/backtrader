### 背景

现在这个测试用例失败了，需要修复，先研究定位一下具体的bug原因，然后考虑根据修复方法建议进行修复。
============================================================
Failed Tests:
============================================================
  FAILED tests/strategies/test_94_mean_reversion_sma_strategy.py::test_mean_reversion_sma_strategy - AssertionError: Expected final_value=172375.61, got 158319.837331632


### 修复方法建议
0. backtrader/sync_and_test.py 这个脚本可以同步一个测试文件的更新到master分支，并调用run_test_with_log.py进行测试，输出日志，方便后续对比。
1. backtrader/run_test_with_log.py 这个运行这个策略，然后对比master分支上的结果，看看origin分支上的结果究竟差在哪里，然后去定位。
2. 如果必要，可以修改测试用例，增加注释，然后方便在两个分支上进行对比。
3. 很可能是ichimoku指标实现的问题，参考macd.py指标实现的方式，实现这个指标。

### 资源
1. 修改当前测试脚本，比如新增了debug信息之类的，可以用backtrader/sync_to_master.py同步到master分支上的对应脚本
2. 可以使用backtrader/run_test_with_log.py这个脚本，对比当前分支(origin)和master分支上运行这个策略的结果，形成日志，放到logs，方便后续对比差异。

### 限制

1. 不允许修改测试用例，尤其是测试用例的期望值,这些期望值都是master版本上验证正确的。
2. 修改过源代码重新测试的时候，最好pip install -U . 重新安装一下。
3. 现在版本的代码和原始的底层实现的逻辑已经有很大不一样了，每个函数的逻辑可能会存在不一样，不能按照master版本的相应函数来实现现在版本的函数。即不允许：restore the master branch's simpler, declarative implementation
### 背景

现在这个测试用例失败了，需要修复，先研究定位一下具体的 bug 原因，然后考虑根据修复方法建议进行修复。
FAILED tests/strategies/test_96_ichimoku_cloud_strategy.py::test_ichimoku_cloud_strategy - AssertionError: Expected final_value=100088.51, got 100189.7366


### 修复方法建议

1. backtrader/sync_and_test.py 这个脚本可以同步一个测试文件的更新到 master 分支，并调用 run_test_with_log.py 进行测试，输出日志，方便后续对比。
2. backtrader/run_test_with_log.py 这个运行这个策略，然后对比 master 分支上的结果，看看 origin 分支上的结果究竟差在哪里，然后去定位。
3. 如果必要，可以修改测试用例，增加注释，然后方便在两个分支上进行对比。
4. 很可能是 ichimoku 指标实现的问题，参考 macd.py 指标实现的方式，实现这个指标。

### 资源

1. 修改当前测试脚本，比如新增了 debug 信息之类的，可以用 backtrader/sync_to_master.py 同步到 master 分支上的对应脚本
2. 可以使用 backtrader/run_test_with_log.py 这个脚本，对比当前分支(origin)和 master 分支上运行这个策略的结果，形成日志，放到 logs，方便后续对比差异。

### 限制

1. 不允许修改测试用例，尤其是测试用例的期望值,这些期望值都是 master 版本上验证正确的。
2. 修改过源代码重新测试的时候，最好 pip install -U . 重新安装一下。
3. 现在版本的代码和原始的底层实现的逻辑已经有很大不一样了，每个函数的逻辑可能会存在不一样，不能按照 master 版本的相应函数来实现现在版本的函数。即不允许：restore the master branch's simpler, declarative implementation

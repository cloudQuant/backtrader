# R7 当前输入与全注册表因果检查

在 `a9141424` 后修复零回看因子的采集边界：`lookback_h=0` 仍须检查当前行声明输入的有限性。公式分支返回有限常数不等于输入有效；不改变公式自身输出或强制历史不足时一律为空。

独立执行（Anaconda base，CPython 3.11.8）：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/unit/test_factor_zero_lookback.py tests/unit/test_factor_panel.py tests/unit/test_factor_sink.py tests/unit/test_factor_research_contracts.py -q
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/integration/test_alpha101_native_data_contracts.py -q
```

- 当前输入、存在标记、窗口恢复、panel/sink 合同：39 passed，见 `zero-lookback-regression.txt`。
- 全 101 公式，6 批 × runonce/runnext，T=320、6 资产：12 passed，245.39 秒，见 `full-counterfactuals.txt`。逐 `(time, asset)` 核对资产重排和未来 40 行行情扰动以前的输出；不排序因子值、不使用离散名次偏差预算。每个公式必须有有限前缀输出。
- 长历史独立数学参考和正式性能在其他证据中分别记录，本记录不替代它们。

# R7 全 101 公式严格验收

本轮撤销 `25396ac4` 测试中的资产值排序比较、名次差值/逆序/受影响行数预算，以及按历史长度放宽这些预算的建议。float64 的细微舍入可以改变下游秩，但不能据此允许一个资产收到另一个资产的结果。

新的测试方法：独立解析测试目录中的论文公式 AST，并由实际指标输入连线重建生产图，检查公式拓扑、字段绑定与资产对应。按拓扑顺序以独立运算复核每个节点；连续结果使用固定 `1e-12 + 1e-10*abs(reference)`，NaN 掩码严格相同；rank、argmax/argmin、窗口极值、delay、比较与分支按已经逐节点核验的实际 float64 输入精确比较。只有通过局部检查的中间值才能供下游参考使用，最终节点不能注入参考。随后验证 factor.outputs 拷贝及 collector 面板，并独立从源数据推导真实 bar 与输入窗口掩码。

相关与协方差的测试参考按输入的 binary64 精确有理值计算，相关的平方根只在测试内使用高精度 Decimal；生产运行时保持 float64。测试既不将近似相等变成并列，也不把合法的近零/近 ±1 相关吸附为特殊值。额外反例拒绝资产交换、NaN 掩码交换、ULP 秩反转、核偏差和错误分支。

主线程独立执行：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/integration/test_alpha101_native_matrix.py tests/unit/test_alpha101_trace_validation.py tests/unit/test_alpha101_reference_contract.py -q
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/unit/test_factor_*.py tests/unit/test_alpha101_*.py tests/unit/test_alpha003_daily_runner.py tests/integration/test_alpha101_native_boundaries.py -q
```

- 长历史与参考合同：26 passed，1251.14 秒，见 `full-matrix.txt`。全 101 × T=320/640/1280 × runonce/runnext，含真实缺行及存在但 NaN 的字段。
- 广泛研究回归：509 passed，67.79 秒，见 `research-final-regression.txt`。包括恢复的 101 个公式错误变异见证、18 个错误分类层级见证、公共 registry 合同、代表公式、CSV/适配/采集及日频分段入口。
- 全注册表的两模式资产重排/未来扰动另见 `collector-counterfactuals.md`（12 passed）。

这些结果关闭相应正确性切片；性能和精确安装产物仍需各自的实测证据。此前失败的首轮研究日志保留在 `full-research-regression.txt`：旧预算断言失败与工具编辑期间的接口不一致均已通过上述最终回归复核，不纳入通过数。

# R7 性能工具验收

工具实现与性能结果分开验收。本记录只证明工具的采样、计时和产物判定合同。

- `scripts/benchmark_factor_research.py`：采集包含在 Cerebro 时间内，单列 `collect` 为 `INCLUDED_IN_CEREBRO`，耗时 null；`panel` 是取回已形成面板的耗时。父进程额外记录完整 wall、采样 CPU、进程树峰值 RSS。评价非 OK、缺依赖、报告缺失不能记成功。
- `scripts/benchmark_factor_research_pair.py`：运行两个冻结源码目录的真实 quick 入口。各例每侧一次完整预热，再运行至少三组交替配对；同样的股票、日历、因子、HTML、评价及默认 PNG。025/026 两侧分别保存旧 dataset 与新 panel，存储格式差异是计划删除能力的明确边界。
- 样本不足、非零订单、缺少有限因子值、评价表空、HTML/PNG 缺失或新 panel 不足六个 CSV 均失败。027 不存在的评价标 NOT_APPLICABLE。减少股票数或关闭默认图表只形成诊断，不能成为正式用户场景证据。
- 026 配置需两侧采用相同、受配套 fincore 支持的 pairwise comparisons；027 的 v1→v2 profile 差异须通过明确 allowlist 登记，仅用于整体重构比较。

主线程独立运行：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/unit/test_factor_benchmark.py -q
```

结果：19 passed，0.57 秒，见 `benchmark-contracts.txt`。20 只入口 smoke 仅验证工具连接，不证明 500 只性能达标。

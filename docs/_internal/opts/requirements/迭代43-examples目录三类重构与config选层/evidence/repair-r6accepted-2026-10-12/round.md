# enforce-copy-acceptance-and-public-dependencies

仓库：`D:/source_code/backtrader`，分支：`dev`，验收父提交：`06e644cd0108496c0b2f9f09c0eda5ec79b9f1e0`。

验收：{"passed": 109, "failed": 0, "skipped": 0, "errors": 0}，组合验收通过（原始两次 pytest exit 为1/0，并非一次全量 exit 0）；原有四个无关脏路径字节/差异保留。证据级别为源码、fake与离线测试，不增加真实账户/正式案例通过。

本轮范围：

- `AGENTS.md`
- `examples/README.md`
- `examples/_support/ctp_legacy_example_support.py`
- `examples/backtest/006_plots/example_bokeh_charts.py`
- `examples/backtest/006_plots/plot_plotly_example.py`
- `examples/unified/013_1_midfreq_cross_arbitrage/README.md`
- `examples/unified/013_1_midfreq_cross_arbitrage/ctp_example_support.py`
- `examples/unified/013_2_highfreq_calendar_arbitrage/README.md`
- `examples/unified/013_2_highfreq_calendar_arbitrage/ctp_example_support.py`
- `tests/unit/test_examples_self_contained.py`
- `tests/unit/test_iteration43_copy_out_runnable.py`
- `tests/unit/iteration43_example_entrypoint_coverage.json`
- `tests/unit/test_iteration43_ctp_legacy_example_support.py`

精确命令、日志/结果见相邻result.json与raw-qa.zip。实际提交哈希汇总到本迭代后续修复复验记录。

Composite acceptance: 97 unchanged successful r6b cases plus 12 r6d reruns. The original r6b exit 1 and its 12 process-cleanup-contaminated failures remain frozen. This is not a claim that r6b exited zero or that 109 cases ran in one invocation.

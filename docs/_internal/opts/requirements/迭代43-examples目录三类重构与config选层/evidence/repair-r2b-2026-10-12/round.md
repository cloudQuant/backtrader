# restore-package-import-and-front-error-guards

仓库：`D:/source_code/backtrader`，分支：`dev`，验收父提交：`b64078971ff4c225aceb0d0925a885cd694e3273`。

验收：{"passed": 54, "failed": 0, "skipped": 0, "errors": 0}，pytest exit 0；原有四个无关脏路径字节/差异保留。证据级别为源码、fake与离线测试，不增加真实账户/正式案例通过。

本轮范围：

- `examples/unified/012_1_midfreq_cross_exchange/run.py`
- `examples/unified/012_2_event_driven_cross_exchange/run.py`
- `examples/unified/013_1_midfreq_cross_arbitrage/run.py`
- `examples/unified/013_2_highfreq_calendar_arbitrage/run.py`
- `tests/unit/test_iteration42_component_boundaries.py`
- `tests/unit/test_iteration42_live_front_failure_evidence.py`
- `examples/unified/012_1_midfreq_cross_exchange/strategy-candidate-manifest.json`
- `examples/unified/012_2_event_driven_cross_exchange/strategy-candidate-manifest.json`

精确命令、日志/结果见相邻result.json与raw-qa.zip。实际提交哈希汇总到本迭代后续修复复验记录。

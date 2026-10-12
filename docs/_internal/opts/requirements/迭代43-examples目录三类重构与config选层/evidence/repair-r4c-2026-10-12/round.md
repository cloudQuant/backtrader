# preserve-tier-and-write-grant-evidence

仓库：`D:/source_code/backtrader`，分支：`dev`，验收父提交：`8fa9abf468da8e36e3c43c14f82a81ba0dc8d3f5`。

验收：{"passed": 101, "failed": 0, "skipped": 0, "errors": 0}，pytest exit 0；原有四个无关脏路径字节/差异保留。证据级别为源码、fake与离线测试，不增加真实账户/正式案例通过。

本轮范围：

- `examples/unified/012_1_midfreq_cross_exchange/run.py`
- `examples/unified/012_2_event_driven_cross_exchange/run.py`
- `examples/unified/013_1_midfreq_cross_arbitrage/run.py`
- `examples/unified/013_2_highfreq_calendar_arbitrage/run.py`
- `examples/unified/013_3_sa_midfreq_simnow/run.py`
- `examples/unified/014_1_ctp_options_lowfreq/run.py`
- `examples/unified/014_2_ctp_options_midfreq/run.py`
- `examples/unified/015_ctp_options_highfreq/run.py`
- `examples/unified/012_1_midfreq_cross_exchange/strategy-candidate-manifest.json`
- `examples/unified/012_2_event_driven_cross_exchange/strategy-candidate-manifest.json`
- `tests/unit/test_iteration43_entry_tier_dispatch.py`

精确命令、日志/结果见相邻result.json与raw-qa.zip。实际提交哈希汇总到本迭代后续修复复验记录。

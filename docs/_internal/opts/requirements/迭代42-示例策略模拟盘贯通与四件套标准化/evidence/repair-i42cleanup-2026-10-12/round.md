# require-confirmed-live-final-cleanup

仓库：`D:/source_code/backtrader`，分支：`dev`，验收父提交：`2edf40cb9b6b9d29d481b6819811e1fff9a5a489`。

验收：{"passed": 211, "failed": 0, "skipped": 0, "errors": 0}，pytest exit 0；原有四个无关脏路径字节/差异保留。证据级别为源码、fake与离线测试，不增加真实账户/正式案例通过。

本轮范围：

- `examples/unified/013_1_midfreq_cross_arbitrage/run.py`
- `examples/unified/013_2_highfreq_calendar_arbitrage/run.py`
- `examples/unified/013_3_sa_midfreq_simnow/run.py`
- `examples/unified/014_1_ctp_options_lowfreq/run.py`
- `examples/unified/014_2_ctp_options_midfreq/run.py`
- `tests/unit/test_iteration42_live_final_cleanup.py`
- `tests/unit/test_iteration42_observation_final_cleanup.py`

精确命令、日志/结果见相邻result.json与raw-qa.zip。实际提交哈希汇总到本迭代后续修复复验记录。

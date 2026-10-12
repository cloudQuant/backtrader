# strict-entry-schema

仓库：`D:/source_code/backtrader`，分支：`dev`，验收父提交：`e96e1962333827a91b03812b7bc8d3484e32d42f`。

验收：{"passed": 50, "failed": 0, "skipped": 0, "errors": 0}，pytest exit 0；原有四个无关脏路径字节/差异保留。证据级别为源码、fake与离线测试，不增加真实账户/正式案例通过。

本轮范围：

- `examples/_support/entry_tier.py`
- `examples/unified/012_1_midfreq_cross_exchange/entry_tier.py`
- `examples/unified/012_2_event_driven_cross_exchange/entry_tier.py`
- `examples/unified/013_1_midfreq_cross_arbitrage/entry_tier.py`
- `examples/unified/013_2_highfreq_calendar_arbitrage/entry_tier.py`
- `examples/unified/013_3_sa_midfreq_simnow/entry_tier.py`
- `examples/unified/014_1_ctp_options_lowfreq/entry_tier.py`
- `examples/unified/014_2_ctp_options_midfreq/entry_tier.py`
- `examples/unified/015_ctp_options_highfreq/entry_tier.py`
- `examples/unified/012_1_midfreq_cross_exchange/run.py`
- `examples/unified/012_2_event_driven_cross_exchange/run.py`
- `examples/unified/012_1_midfreq_cross_exchange/strategy-candidate-manifest.json`
- `examples/unified/012_2_event_driven_cross_exchange/strategy-candidate-manifest.json`
- `tests/unit/test_iteration43_entry_tier.py`
- `tests/unit/test_iteration43_entry_schema.py`

精确命令、日志/结果见相邻result.json与raw-qa.zip。实际提交哈希汇总到本迭代后续修复复验记录。

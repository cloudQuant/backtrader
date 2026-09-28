# G4 CTP native lifecycle receipt 作者候选（2026-09-27）

**状态：r1 作者候选已被[独立 QA 拒绝](ctp-native-lifecycle-receipt-r1-independent-rejection-2026-09-27.md)。G4 尚未关闭，也不是 native clean-close 验收。** 独立 exact-object 探针在 Trader `Init` 期间读到 receipt 的 API generation 为 0、client/SPI 已为 1，receipt 的 epoch/API source ID 仍为空；后续 fake clean 也未捕捉这个不一致。作者的 65 项通过记录保留为局部结果，新 r2 将另行冻结与复验。

候选位于 `D:\temp\iteration41_g4_native_lifecycle_receipt_candidate_20260927`，基于干净 SDK 源 `D:\q\e` 的 HEAD `29f8ff171f61a71038328a7067e0909bf44774b2`。基线 `client.py` SHA-256 为 `bf915128c41da83efdff517e3ea711c43d7555406bd831a0dfcd775b64840d1c`。本候选**不是 e75 wheel 的源码**；e75 对照来源 `client.py` SHA-256 为 `2d31bf75b801847d185db5cbcbf284752736e96b4874449fb34bdab0dc5cbf09`，不得混用版本或制品身份。

候选只改 `src/bt_api_ctp/ctp/client.py` 并新增 `tests/test_ctp_native_lifecycle_receipt.py`。实现为 MD/Trader 客户端提供不可变的逐代次 receipt，记录 API/SPI/session 身份，以及 `RegisterSpi` 注册/解绑、`Init` 是否进入和返回、`Join` 返回类型/代码或异常、`Release` 恰一次尝试和返回/异常。未完成、异常、超时或不确定状态不报 clean；失败后的释放不会重试。receipt 不把进程或 Job 终止当作 native 清理证据。

## Fake-only 验证

从候选根目录执行：

```powershell
$env:PYTHONPATH='D:\temp\g5-r3-test-guard;D:\temp\iteration41_g4_native_lifecycle_receipt_candidate_20260927\src;D:\source_code\backtrader'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest --noconftest tests/test_ctp_native_lifecycle_receipt.py tests/test_ctp_shutdown.py tests/test_md_startup_locking.py -q --tb=short --junitxml='D:\temp\iteration41_g4_native_lifecycle_receipt_evidence_20260927_r1\junit.xml'
```

结果为 **65 passed、2 warnings、exit 0**。Ruff、测试文件格式检查、`py_compile` 和 `git diff --check` 均通过。native import guard 在测试期间拦截 `_ctp` 导入；测试未调用真实 CTP、provider、凭据或网络。两条 warning 分别是插件禁用时 pytest 不识别的既有配置项，以及 guard 拦截 native extension 的提示。

历史基线运行曾间歇性失败于 `test_stop_during_first_register_spi_blocks_all_later_startup_calls[trader]`；该观察发生在本候选改动之前，未通过跳过或修改测试规避，最终焦点回归通过。历史失败的原始日志未随冻结材料保留。

同步 native 生命周期调用仍可能阻塞；该 receipt 只报告调用观察，不提供有界 supervisor 证明。因此不得据此启用默认 CTP route、声称 G4 PASS 或宣称已验证真实 native clean-close。

逐项源文件、测试、基线、环境、日志、JUnit、静态检查与 guard 的 SHA-256 清单见[机器回执](ctp-native-lifecycle-receipt-author-candidate-2026-09-27.json)。原始冻结材料在[ZIP 归档](ctp-native-lifecycle-receipt-author-candidate-2026-09-27.raw.zip)，SHA-256 `b7bda9269601492c04972c3446d443258269f802faabe2a8e38f4d6fb25e61dd`；共 12 个文件、14 个 ZIP 条目，`ZipFile.testzip()` 返回 `None`，且归档成员逐项大小和 SHA-256 校验通过。

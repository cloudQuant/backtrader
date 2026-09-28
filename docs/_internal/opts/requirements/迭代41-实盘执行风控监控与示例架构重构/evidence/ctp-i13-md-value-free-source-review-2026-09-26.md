# I13 MD 原生身份字段值脱敏源码候选（2026-09-26）

状态：`SOURCE_REVIEW_ONLY / NO_WHEEL / NO_PROVIDER / NO_WRITE`。

隔离候选位于 `D:/source_code/bt_api_ctp_i13_md_value_free_review`，提交为 `297f37e2027048b61f1dfd50effe5a0d025a2ecc`。审阅清单为 `docs/i13-md-readonly-candidate-manifest.json`，原始字节 SHA-256 为 `f6d71880decf39bc252432a72bafb9b3ae26fe0056ebd3081b8f3c19efa6607e`。独立只读复核确认：工作树干净，`core.autocrlf=true` 下清单的 14 个有序条目均与 Git blob 及 Windows checkout 原始字节一致，base→候选的所有变更路径都在清单中。`.gitattributes` 对本候选的代码、测试、文档与生成器固定 LF；三个未修改的 vendor header 保持原有 CRLF blob。一次 Windows clean sparse clone 重生的清单摘要相同。

源码新增原生 `BrokerID[11]`、`UserID[16]` 与 `TradingDay[9]` 的有界 shape 分类，用于下一次精确制品下的只读诊断区分空、有效、畸形或不可读字段。该候选不能解释历史真实回调中空身份字段的来源，也不能证明当时加载的是相同扩展。request ID、订阅 ACK、首个 tick 和 native Join 完成分别验收；不能从其中一项推断其他项。

Ruff 与 `py_compile` 通过。最终源码 checkout 没有 `_ctp.pyd`，因此候选原生/包级 pytest、C++/SWIG 构建、wheel RECORD/ABI、真实 MD 会话和有序 native close 均为 `NOT_RUN`。此前使用另一份非候选扩展的 154 项 fake 测试只作历史诊断，不属于本提交的通过证据。

这份 14 条目的 SDK **源码审阅清单不是**主仓 I13 父启动器要求的 `backtrader_runtime/ctp_i13_source_manifest.json` 运行时闭包清单；schema、路径和覆盖范围不同。它只覆盖 SDK `src/bt_api_ctp` 下 78 个 Python 文件中的 3 个，不能作为父启动器的 `I13_SOURCE_MANIFEST_SHA256` pin。下一阶段须独立固定完整源码、解释器、SDK/base/CTP 扩展与安装来源，建立父启动器要求的外部 descriptor、代码 pin、Windows Job/总期限，并证明原生 Join/Release；在此之前默认 `preflight` 与所有写入入口保持关闭。

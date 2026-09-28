# Parent 76d5e0e 双构建 wheel（2026-09-26）

Parent commit `76d5e0e60883263e0e79b67df321e7053ed46179` / tree `9371e8e04bafb18bed8e2ee7750a17441800f182` 从两份独立 `git archive` 解压目录离线构建。两个 `bt_api_py-0.15.5-py3-none-any.whl` SHA-256 均为 `3d4ccf8560f28dc6f0279860ca6257e4980b7c6efb0f9932fe66c98b681a660d`；根代理复核 156 个 ZIP 成员字节完全相同。

这版显式转交 Gateway `server_admission` 与 `writer_authority`；未加 fallback。作者源码 focus 为 4 passed，另有实际 Router 缺失 gates 的两项拒绝检查；这些不是本构建步骤执行的消费者测试。

构建环境与命令、固定 epoch、日志、源码归档及成员清单都在证据包。wheel 为纯 Python，不含 native 扩展；依赖声明保留。根代理核对制品与原始回执，没有再次构建或创建统一消费者。原 parent checkout 四个既有 dirty gitlinks 保留，归档未包含其工作树更改。

该 parent wheel 不包含 Execution V18/V19，也不证明完整 base/SDK/execution/risk/monitor/gateway 组合兼容。统一 clean consumer、真实生命周期和 provider 验收仍待完成。


## 原始证据

- [机器回执](ctp-parent-76d5e0e-repro-wheel-2026-09-26.json)
- [原始证据包](ctp-parent-76d5e0e-repro-wheel-2026-09-26.raw.zip)，SHA-256 `2bc052db22787a7bc1e2b9752be92351c341e19b653afbdd9af7dc61d6f847fd`。

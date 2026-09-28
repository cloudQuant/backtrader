# V18 主仓候选与 fake SDK 组合（2026-09-26）

**局部结果：33 passed，0 skipped，1 warning，2.91 秒。** 独立代理复制主仓 runtime 与 I9 测试，在真实 V18 SQLite Store、SDK `29f8ff1` 的 TraderClient 和 fake TraderApi 之间验证撤单后置条件。

新增场景中，初始报单之后收到撤单 ACK，目标仍 PARTIALLY_FILLED。第三个 submit 已入本地队列，直接调用有会话约束的 Store claim 被拒绝，fake `ReqOrderInsert` 计数保持 1。随后确切 CANCELLED order callback 与此前 trade 累计数量一致；同一个第三 submit 可经 candidate dispatch，计数成为 2。ACK 本身不能解除阻断。

限制：冻结候选的 `dispatch_next()` 会把 READY claim 错误归为 UNKNOWN/poison，因此本轮对等待期的拒绝采用 Store typed claim 观察，不能宣称候选自动重试等待流程通过。该问题已交下一切片修复。V18 按 environment 分账户，本轮也不证明跨模式占用、关闭重启或生产账户排他。

使用明确 PYTHONPATH 的源码组合；没有额外 runtime import-origin/native-module 审计。SDK import 尝试加载 `_ctp`，因为源码内没有匹配 Windows 扩展而产生预期 warning；实际测试用 fake API，未执行 provider/native 操作。日志另保留运行前 pytest-asyncio 配置 deprecation 提示。此路径直接组合 Execution Store 与 SDK client，不是 parent BtApiStore 的真实派发验收，也不是安装 wheel 证据。

根代理复核冻结文件、manifest 与 JUnit，未重复测试。原始代码与测试副本完整保留，后续编辑不覆盖这份结果。

原始 manifest 在 JSON 数组后多出字面量 `\n` 两字节；根代理仅在解析时去除这两个已确认字节，核对全部 100 份文件，证据包仍保留原始 manifest 字节。

## 原始证据

- [机器回执](ctp-v18-main-sdk-fake-composition-2026-09-26.json)
- [冻结源码、测试与日志](ctp-v18-main-sdk-fake-composition-2026-09-26.raw.zip)，SHA-256 `9156ad3fa7246c590d43d4c0f46ba59492bd17713156fa9a4f74238a480ece56`。

# G1 output-channel r3：独立拒绝

15 项独立焦点通过，但独立脚本向 reader 提供伪造的 Job-empty `SimpleNamespace`，在绑定 worker 仍活跃时取得 261 字节 frame。构造中 `_begin_accept` 失败还可能留下管道/overlapped 句柄。r3 不接受为可信服务输出通道。此反例说明 helper API 合同缺口，未证明外部服务调用者在计划中的受保护组合里一定可注入参数。

[机器记录](ctp-g1-output-channel-r3-independent-rejection-2026-09-27.json)与[原始归档](ctp-g1-output-channel-r3-independent-rejection-2026-09-27.raw.zip) SHA-256 `d4267de8a0129572e69e6efe61ea1248cfe5e42d707a90b9448b8a762eb008c0`，10 项。G1 仍 `NOT_PASSED`。

# G1 two-stage r4 独立审查

日期：2026-09-27  
裁决：R4 本地惰性候选的独立检查通过；**G1 CLOSED**，不得据此开放普通 preflight 或默认 live route。

## 冻结输入与归档

候选清单 SHA-256：`805d066b74ec7eee0519993395d2078605ef46fbe2b1a2e63ff11aafd82dc4a1`。R3 基础清单 SHA-256：`e30f2f21ab714f90c82ce33bdf9c290a533477f19fcd59f5b8d931238c38b399`。独立副本在测试前后均逐项核对 **30/30 payload** 的长度及 SHA-256。

可复核原始包：[R4 independent QA ZIP](ctp-g1-two-stage-r4-independent-qa-2026-09-27.raw.zip)，SHA-256：`3bfee569699ca599a438adc200bec8b1cdbc37e7f8949901874ff9cbf1e02633`；[ZIP 内容 SHA 清单](ctp-g1-two-stage-r4-independent-qa-2026-09-27.raw.contents.json)，SHA-256：`369a0a648060d32bbae54ff1c81d815d0d6339be539060262b73a5687e0aa6cf`。包含候选 30 项、独立 QA 原始收据/日志/探针共 14 项，合计 48 个文件；ZIP `testzip()`、所有 48 项哈希及包内 manifest 的 30 项 payload 校验通过。

## 独立复核结果

- 相关四文件完整集：**85 passed**（CPython 3.11.5，禁用 pytest 插件自动加载）。
- 七个定向目标：**7 passed**，覆盖 256 KiB 大小边界、AST 文本与来源绑定、三种协调器 exit/frame 组合及嵌套 Job 计数。
- 伪造外层 exit code 2、内层 frame 声称 OBSERVED 的显式负例：**1 passed**；服务结果保持 UNKNOWN。
- 两个目标文件 `py_compile`：通过，exit 0。
- bootstrap：256,988 / 262,144 bytes，余量 **5,156 bytes**。
- QA AST 文本篡改探针：基线文本接受；只改嵌入文本而保留外层 digest 时，以 `embedded_support_digest` 拒绝；同时重算外层 digest、但保留文件执行 digest 时，以 `embedded_support_source_digest` 拒绝。探针不执行生成的 bootstrap。

**85 + 7 + 1** 是三次独立 pytest 调用的精确计数；最后 1 项是七目标集中的伪造 exit-2 负例单独重跑，不代表 93 个互不重复的测试。

## 边界

该候选的服务与 Job 事实仍是 fake/inert 模型。未验证 Windows OS containment、真实 SCM 部署或服务 ACL；prewarm/setup 与同步 watchdog deadline 缺口仍未解决。未接触 CTP、凭据、SDK/native/provider、网络或 token session。以上结果不构成真实 G1 接受，也不改变 G1 CLOSED 状态。

作者候选说明见[ R4 作者页](ctp-g1-two-stage-r4-author-2026-09-27.md)；机器收据、JUnit、逐项审计、运行日志与 AST 探针均在上述 ZIP 中。

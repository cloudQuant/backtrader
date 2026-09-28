# Execution R3r2 撤单 claim 独立复核

**局部接受：**29 份冻结源码/测试逐字节匹配；隔离包 `278 passed / 2 skipped`。两个 skip 为可选 SDK bridge 测试：原冻结 fixture 的假 login 回调缺少 BrokerID/UserID；QA 单独补齐这两个字段后 `2 passed`，未修改冻结源码。

claim 返回整数 `0` 时撤单 provider 调用数为 0；provider 本身返回 `0` 时调用数为 1。两条路径均保持 UNKNOWN，禁止重试、释放和结算。精确类型的 claim receipt 绑定 permit、scope、cancel ID、intent fingerprint；八种畸形值和异常都在原生撤单前拒绝。

结论只适用于离线 fake/source 合同。原子终态事件、父包 issuer、主仓正向整合及真实 CTP 均未验收；默认 `NO_WRITE / LIVE_NO_GO` 不变。

[机器记录](ctp-execution-r3r2-cancel-claim-independent-review-2026-09-27.json)与[原始归档](ctp-execution-r3r2-cancel-claim-independent-review-2026-09-27.raw.zip)保存冻结清单、独立日志和精确来源；归档 SHA-256 `4c3656984c5df9fa7fd2c707c5d481a0c8a4fec39bfec126f21da70e7bec25e9`，共 66 项。

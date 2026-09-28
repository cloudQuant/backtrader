# G6 v2 字段绑定与 READY 延后重试独立复验

**结论：限定源码合同通过，测试文件仍有一项 lint 问题。** 独立代理在冻结六文件上复跑 **75 passed / 0 failed / 0 skipped**。这不是最后原生调用时的许可复核、统一 wheel、真实会话或写入准入。

## 来源与结果

- 六文件 manifest：`1ea2e2ec890fc1f65cf9083b84621895944ef6c6fc834773118de9930b90320f`。
- 独立 QA manifest：`dee0fb729e1f49398a85892cb5e881effb63b8a2426ce37ccb5217d140aa96f1`。
- 执行库使用 V18 r0，Store SHA `25980518e1b7aae5ce13e3531ab854771ab5d036df0209cddde08508124e8206`；执行库 `0.2.0` metadata 是明确标注的 QA 源码 shim。
- CTP 为 clean SDK `29f8ff171f61a71038328a7067e0909bf44774b2`；parent 为 `76d5e0e60883263e0e79b67df321e7053ed46179` 的源码，base gitlink 源码版本为 `0.15.4`。parent 的四个既有 gitlink dirty 状态已记录，不能称整个 parent worktree clean。
- 独立来源记录确认 authority、resolver 和 I9 三模块来自冻结副本。测试有 pytest-asyncio 配置提示及无匹配 Windows `_ctp` 扩展的 warning；扩展未加载。不能把这次 focus 写成“没有尝试原生导入”。

独立补充 runner 使用真实 V18 SQLite Store、冻结 authority/resolver 和临时 Ed25519 密钥。两个登录 Broker/User 错配与六个请求字段错配均具有实际行 action digest 绑定的签名，但在 claim 前被拒绝，行保持 `READY`、owner 保持 `ACTIVE`，native dispatch 为零。匹配配置的控制组进入 `CLAIMED`，也没有调用 SDK Req。

六字段为 BrokerID、InvestorID、UserID、InstrumentID、ExchangeID、CombHedgeFlag。该矩阵关闭了此前“签名有效但与密封配置不符仍 claim”的具体反例；不是外部账户身份或共同快照的证明。

75 项还覆盖 READY-only defer 的本地合同。CLAIMED 后的 expiry/revocation/fence 变化与调用 SDK 前的复核属于后续 r3，不由本回执证明。最终检查与 Req 的外部原子栅栏也仍未建立。

## 质量检查与保留记录

三个生产模块的 Ruff check 通过，六文件 format-check 通过；六文件一起 check 时，冻结 integration test 第 975 行存在一项 E731（局部 lambda 赋值），未修改冻结文件。额外 runner 最初在 stage 前读取行的顺序错误有独立失败日志，修正 QA runner 后的有效矩阵另行保留。

根代理重新核对了 manifest 中 **25** 个文件哈希、独立 JUnit 的 75 项结果以及八负一正的原始输出；没有重新执行这组测试。[机器可读记录](ctp-g6-v2-bound-fields-defer-independent-review-2026-09-26.json)保存全部来源与限制，[原始归档](ctp-g6-v2-bound-fields-defer-independent-review-2026-09-26.raw.zip)包含六文件源代码、作者和独立日志、JUnit、runner、来源记录与 manifests。

归档 SHA-256：`5dc9d488261c795f3db2f119efe313e7db39b5fa56d3b1fe9912b13bd6796486`，共 26 个条目。

本记录不访问私有配置、真实密钥/撤销服务或 provider，不解除 `NO_WRITE / LIVE_NO_GO`。

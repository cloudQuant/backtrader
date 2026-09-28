# V20 共享账户 runtime r1：独立源码验收

105 份冻结文件全部匹配 manifest；独立复跑 `84 passed / 2 expected xfailed / 0 failed`，实际候选模块和 Execution/SDK/base 导入来源经进程内核对，未加载 CTP 原生扩展。模拟与 live 对同一封存账户使用既有同一个 journal 路径；永久 family owner 阻断跨模式重启且拒绝不改库字节。非空旧 journal 的 `legacy_scope_missing` 在 WAL/可写打开前拒绝；旧入口也拒绝 V20 库而不改变字节、journal mode 或 schema。候选未进入默认 registry。

这是 source-only metadata shim 与 fake client 的未注册候选。两项 expected xfail 仍证明最后配置复核与原生调用之间的竞态未关闭；没有安装 wheel、受信外部账户排他或真实交易证据。[机器记录](ctp-v20-shared-account-runtime-r1-independent-review-2026-09-27.json)与[原始归档](ctp-v20-shared-account-runtime-r1-independent-review-2026-09-27.raw.zip) SHA-256 `c96e0a10da5339c6ddf03fae712e1cf74481e4079d1f74408d7fd70a763a69e4`，共 121 项。`NO_WRITE / LIVE_NO_GO` 不变。

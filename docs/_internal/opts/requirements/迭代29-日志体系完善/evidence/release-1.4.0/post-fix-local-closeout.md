# 1.4.0 修复后本地候选证据

状态：**HISTORICAL_PRE_FINAL_LOGGER_REPAIRS**。这是最终 logger 修复之前的本地候选记录，不是当前工作树或最终 commit 的包验证、远程 CI、tag、
Release、实盘、SimNow 或盈利验收。当前最终 logger 证据见
[line-system-logger-remediation.md](line-system-logger-remediation.md)。

master 为 **NOT_TOUCHED**。本次主仓唯一允许的提升路径是 dev -> development。

| 门禁 | 状态 | 证据和边界 |
| --- | --- | --- |
| 质量 | HISTORICAL_SOURCE_STALE | Ruff、Black、isort、459 个 backtrader 源文件的 Mypy、Bandit Medium/High 均通过；最终 logger 修复后必须重跑。 |
| 固定公开 SDK 的完整功能套件 | HISTORICAL_SOURCE_STALE | 5,581 passed、1 skipped、0 failed，315.69s；JUnit 5,582 cases、0 failures、0 errors、1 skipped。最终 logger 修复后必须重跑。 |
| 未安装 SDK 的完整功能套件 | HISTORICAL_SOURCE_STALE | 5,102 passed、203 skipped、0 failed；JUnit 5,305 cases、0 failures、0 errors。203 个跳过为 bt_api_py 缺失 187、bt_api_ctp 缺失 15、既有 abs/runonce 递归 1；最终 logger 修复后必须重跑。 |
| 前后配对性能 | HISTORICAL_SOURCE_STALE | 两个冻结基线各 9 对样本、每样本 5 次执行；五种负载中位差均在 5% 预算内，RSS 和两种冷导入预算均通过。最终 logger 修复后必须重跑。 |
| 三个外部 SDK | PASS_PUBLISHED | bt_api_base 0.15.4、bt_api_ctp 2.0.2、bt_api_py 0.15.3 已完成发布和独立验收。 |
| 最终 wheel/sdist 与树外消费者 | PENDING | 必须从最终提交重新构建，不能复用 pre-close 工件。 |
| dev -> development、远程 CI、tag、Release | PENDING | 均须绑定最终精确提交；不得触及 master。 |

候选的 459 个框架 Python 文件树 SHA-256 曾为
ab5189364dc082d3180f0074d5dc6c68d1aa5c9dacc5975f4726c699f86432d4。
它仅绑定此处的历史性能结果，不能替代当前最终源码或未来最终提交、包的指纹。

## 原始产物定位

完整日志和 XML 不复制入仓库。以下哈希允许在原始目录核对：

| 产物 | SHA-256 |
| --- | --- |
| /tmp/backtrader-release140.zbR30K/functional-with-sdk-postfix.log | a3b1cb7ff2a8cc1282e6473ef7518413e9746c7cbc699701e2c8e887005afd82 |
| /tmp/backtrader-release140.zbR30K/functional-with-sdk-postfix.xml | 3b0191e89ecded8194d9ccdb752c972bd5322dcc564b17d876fcac478d8454ef |
| /tmp/backtrader-release140.zbR30K/functional-with-sdk-postfix-provenance.json | b99881fa06dc962cc59268aa48904c10977f1594f1da032671f7d64854fd125a |
| /tmp/backtrader-release140.zbR30K/functional-without-sdk-postfix.log | 6f2f269e3a308cf647a25bb3b02348b8994e2bb73b077cc7eb23463ef6710834 |
| /tmp/backtrader-release140.zbR30K/functional-without-sdk-postfix.xml | 6aa195c6cf97b0935f96597bf040f976c764edbbf2dd530406fa6c2faa621b64 |
| /tmp/backtrader-release140.zbR30K/no-sdk-site/sitecustomize.py | e65fab6377d0b94bd9c35f3faf234c01d8de3e4f68b7d9c2e59149c3f9062368 |
| /tmp/backtrader-release140.zbR30K/performance-paired-fixed-source-current.json | 9f20aafce06caa2af48ce5f0e33e492fb6a7147e53820a8ec4f8a2e85f130b90 |
| /tmp/backtrader-release140.zbR30K/performance-paired-fixed-source-current-summary.json | 0067ad072713cf9cbd8e122d750881794b66cac6e3299001201be6e9b61ae8a3 |

acceptance-snapshot.json、pre-close 包记录、旧 no-SDK 摘要和首次/复测的
配对性能 JSON 均是历史快照，保留原观测，不用于覆盖本页的当前状态。

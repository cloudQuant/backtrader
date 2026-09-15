# 1.4.0 联合验收紧凑证据

当前状态：**PENDING_FINAL_GATES**。最终行系统 logger 修复、`lineiterator` 生命周期能力 guard 和 locator 兼容回退已经产生新的源码快照；此前完整功能套件、配对性能和本地质量仅是较早快照的历史证据，必须从最终冻结源码重跑。最终精确提交包、dev -> development、远程 CI、tag 与 Release 尚待执行。主仓 master 为 **NOT_TOUCHED**。权威进度见[联合验收记录](../../1.4.0联合验收与发布记录.md)。

| 证据 | 范围和限制 |
|---|---|
| [line-system-logger-remediation.md](line-system-logger-remediation.md) / [JSON](line-system-logger-remediation.json) | 当前四文件源码绑定：AST 276（64/101/24/87）、80 个有界且脱敏的恢复 handler、10 个启动 ImportError 排除、无 `logger.debug`/`exc_info=True`；另含 `lineiterator` 生命周期能力 guard 和 locator 两条限流兼容回退，定向 59 passed。完整门禁仍 PENDING。 |
| [post-fix-local-closeout.md](post-fix-local-closeout.md) / [JSON](post-fix-local-closeout.json) | 修复前本地候选的历史证据：公开 SDK 5,581/1、无 SDK 5,102/203、配对性能和原始 /tmp 产物哈希。最终 logger 修复后不可作为当前候选 PASS。 |
| [acceptance-snapshot.json](acceptance-snapshot.json) | 历史 pre-close 快照；保留旧 5,554/1/8 与 5,079/203/1 诊断，不代表当前结果。 |
| [artifact-manifest.json](artifact-manifest.json) | 历史 pre-close 归档的来源/归档哈希；不把旧包或带后续修订的副本当作最终提交工件。 |
| [final-source-hashes.json](final-source-hashes.json) | 先前登记的框架源码指纹；不是未来最终提交、SDK 工作树或最终包的自动证明。 |
| [merge-audit.md](merge-audit.md) / [JSON](merge-audit.json) | 历史 master 对照与兼容处置；它不是 master 合并计划。 |
| [logging-exemptions.md](logging-exemptions.md) / [JSON](logging-exemptions.json) | 23 个 broad 与额外 18 个窄异常的历史静态理由；其中四个行系统文件已由最终修复记录明确取代，静态审查不替代测试。 |
| [performance-paired-round1.json](performance-paired-round1.json) / [retry](performance-paired-retry.json) | 修复前两轮完整样本，保留为历史；当前性能结论以 post-fix closeout 为准。 |
| [wheel-consumer-pre-close.json](wheel-consumer-pre-close.json) / [sdist](sdist-verification-pre-close.json) | 旧包消费者记录；最终精确提交重建和消费者仍待执行。 |
| [external-release-readiness.md](external-release-readiness.md) / [发布提案](sdk-publication-proposal.md) | SDK 发布前的历史审计与提案；三个 SDK 当前均已发布。 |

原始目录：/tmp/backtrader-release140.zbR30K/。大型构建日志、测试 XML、SDK 源码工作树、安装树和回滚 bundle 不复制到 Git 证据目录。历史 M0 未覆盖。最终包、development 远程 CI/tag/Release 和 master NOT_TOUCHED 的独立读回将由主任务追加。

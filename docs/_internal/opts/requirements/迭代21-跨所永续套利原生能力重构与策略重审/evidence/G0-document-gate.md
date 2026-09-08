# G0 文档与基线门禁

> 执行日期：2026-09-07
> 结论：`PASS`
> 2026-09-08 备注：本文仅是历史 G0 收据；当前实施/Gate/研究状态见
> `final-implementation-review.md`，不回写本收据的基线事实。

## 文档完整性

下列文件已创建并通过独立审阅：

- `SPEC.md`
- `需求文档.md`
- `设计文档.md`
- `验收文档.md`
- `任务.md`
- `追踪矩阵.md`
- `.decision-log.md`

自动一致性审计结果：

| 项目 | 结果 |
|---|---:|
| CAP ID | 10，唯一 |
| FR ID | 58，唯一 |
| NFR ID | 8，唯一 |
| 追踪行 | 66，覆盖全部 FR/NFR |
| AC ID | 119，唯一且均被引用 |
| TASK ID | 42，唯一且均被引用 |
| 决策记录 | 20 |
| Markdown 表格 | 列数一致 |

独立 reviewer 结论为 `PASS`；没有发现孤立 P0/P1 需求。

## 基线冻结

- Backtrader 基线：`dev`，HEAD `ab1ae150f73199fbd64449eb7c43fd1f45a29c5d`。
- `bt_api_py` 基线：`master`，HEAD `2be8dbc25b0f49f4734ad337fcd7abe53840c3b9`。
- 两个 dirty checkout 的 branch、HEAD、submodule、status、diff/name-status/stat 已写入
  `.git/iter21-evidence/baseline-manifest.json`。
- 两个工作目录已切换到本地分支 `codex/iter21-cross-venue-arbitrage`；没有 reset、checkout
  文件或回滚用户改动。
- 实施 allowlist 按 SDK、venue plugin、Backtrader Core、两个策略、迁移和验收分组；不相关
  的 013、CTP 认证和工作区配置改动不纳入迭代结论。

## 策略和 support 决策

- 现有 012_1 的 z-score 只作 telemetry，不能作为候选；现有 012_2 是 012_1 的空子类，不能
  通过 HFT 独立性门。
- `cross_exchange_arbitrage_support` 不整包移动。逐对象处置见
  `evidence/support-disposition.md`。
- 策略阈值、切分、成本和 HFT 名称门已在查看新捕获的价格/收益结果之前写入
  `evidence/research-preregistration.md`。
- G0 只允许进入编码，不证明 G1-G5、收益或实盘准备状态。

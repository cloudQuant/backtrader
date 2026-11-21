# R71-112b XPeriodCandleColor 指标上游批量计算小轮

日期：2026-11-22。状态：**限定 Indicator 上游 once 修复已提交，独立复审 GO_NARROW_UPSTREAM_ONCE**。本记录不代表 R71-112b、全部指标、账户或实盘验收。

## 范围与固定版本

- 仓库与分支：`D:/source_code/backtrader`，`dev`；本轮提交 `5c24f55d2471779947831430983a009c5f1633fc`，实际父提交 `bb4771709dff9f1c9c7a45c74829ad64eb76c3a5`。提交只包含产品源码和新增测试两个路径。
- 独立复审以公开 `c5fc2e7e954eae104d4acae5accdd9bf30e9c44d` 导出无 `.git` 的隔离源码并应用冻结补丁；该基线是实际父提交的祖先，两者之间目标指标源码、两个既有预热测试、两份历史策略和公开历史 CSV 均无 Git 差异。冻结补丁 `D:/temp/i71_xperiod_once_c5fc/xperiod_indicator_once_candidate.patch` SHA-256 `960281b77680e711c4b761c93b042d976d4ca29018fced2d41469b3efd57c3ba`；临时文件不是产品依赖。
- `backtrader/indicators/contrib/shared_strategy_indicators.py`：提交 blob 69,391 字节，SHA-256 `0d37b925f31162753e3b2433218aed0893efab12f4df5b7cf33599a9df1972ed`；Windows 工作区及独立测试候选原始字节为 71,315 字节，SHA-256 `0002048865d2af7145b93a67a66e3f3e2d30b4bec143d1a73ce9df04b46a6fe0`，CRLF 规范化为 LF 后与提交 blob 相同。
- `tests/unit/indicators/test_iter71_xperiod_indicator_once.py`：提交 blob 11,346 字节，SHA-256 `9c955017f9a1efad38ff5b23bcdde19ea44b7566165acd15d6f7211d22ef454f`；Windows 工作区原始字节为 11,667 字节，SHA-256 `d454996c7c5c7b99965797e0fcfa67cffe1acd018cf7e1bf38bd9769571c8478`，CRLF 规范化后与 blob 相同。

此前当多线 Indicator 是 `XPeriodCandleColor` 上游时，批量 `once_via_next` 的游标可能停留在 `-1`，成熟输出的 `xopen` 仍为 NaN、颜色可能为 2；普通逐根同样输入有有效值。本轮在该上游类型的批量回调中逐点对齐输入与子线游标，调用原有的动态回调，并恢复临时对齐前的游标；普通 Feed 路径继续委托原批量代理。此前最小周期小轮见《R71-112b-XPeriodCandle最小周期复核-2026-11-22.md》；本轮覆盖成熟值，不将预热通过当作成熟值通过。

## 测试与独立复审

作者在公开隔离候选上使用 Python 3.11.5 和 3.14.2，各报告 **68 passed、1 条既有 Quandl 弃用警告**：新增专项 14 项、独立成熟公式 16 项、独立共享慢时钟 2 项、既有最小周期 30 项、图链边界 4 项及两份历史策略各 1 项。这些是组合运行的同一批测试，不再相加为独立样本。作者以 `python -B -m pytest -q --noconftest ... --tb=short` 在候选快照运行；未因此声称进程安装了额外文件、网络或子进程 guard。

独立复审在公开基线归档上应用上述冻结补丁，Python 3.11.5 下：

- 冻结的新增专项 **14 passed**，另有一条既有 Quandl 弃用警告。它覆盖所测子类动态回调和 `advance` 钩子、分段重算、异常、共享上游、慢 Feed、缺失行情和真实严格因子样本；具体边界以各测试为准。
- 另以独立脚本运行真实 Cerebro，上游两级均值、五条指标输出及下游 SMA 分别按独立公式比较；包含不同窗口、`ma_length=1`、普通及非正周期、共享慢时钟源与两个不同 XPeriod 消费者。**18 passed、1 条既有警告**，逐根和批量均检查成熟值；这 18 项也包含在作者的 68 项之内，不应重复相加。`test_xperiod_mature_independent.py` SHA-256 `b7e2e6f6d4767e9cc5c555667ef27c4ac7ac750c9bf1a9771349ea999d30ffb0`；`test_xperiod_shared_clock.py` SHA-256 `c98501e47ba7a5a756f39e1fcfb210706bcf5a35fc6130882a77d319c2feb980`，两者位于 `D:/temp/i71_xperiod_independent_535e/`，为本机临时复审材料。
- 自定义 Indicator 上游的 `advance` 钩子独立观察，在所测批量图中，基线与候选的 **88 条**四线游标调用前后事件和最终四线游标相同。脚本 `D:/temp/i71_xperiod_independent_535e/advance_observation.py` SHA-256 `384e98f6176496eb986e0bb4bc728aa38b66f7d4ba0c76ef92298638d51a3419`。这不证明所有自定义游标、并发或重入行为。
- 真实 `FactorStrategy` 对所测有限和单根 close NaN 场景比较了两模式五线；另在已运行完成的严格上下文中向内部 SMA 数组注入 Inf，并直接调用 `child.once(12, 13)`，确认抛出 `FactorComputationError`、其 cause 为 `ArithmeticError` 且该线游标恢复。这不是原始 Feed Inf 的端到端证明，也不是 strict 数值域全覆盖。普通子类 `next` 注入 `RuntimeError` 的测试检查所测源与四个 SMA 的游标恢复，不证明已写输出原子回滚。
- 人工 `once(12, 20)` 的有限样本检查该区间重算后的输出和源、子线、输出游标；不推断任意分段、嵌套或重入均已通过。

## 公开历史策略对照

独立复审以 `tests/datas/XAUUSD_M15.csv`（SHA-256 `d364dea806a6ef634277184d1edc71fb90216fadacf673f70ea9706c55a1f51f`）运行基线和候选，两份策略各分别比较 next/once。独立脚本 `D:/temp/i71_xperiod_independent_535e/history_review.py` SHA-256 `3e489139a40c0bd052b10346117e203fdf5b2d5d280cc83d5886cf86b4c8c231`。

| 策略 | `bar_num` | 订单 / 交易通知数 | 最终资产 |
| --- | ---: | ---: | ---: |
| `0002_0343_exp_xperiodcandle_x2` | 1383 | 498 / 166 | 998519.4 |
| `0003_0344_exp_xperiodcandle` | 6032 | 276 / 92 | 998414.6999999993 |

所测基线与候选、两种模式的上述计数和资产一致。订单通知仅比较所记数据长度、时间、状态、买卖方向、创建数量和价格、成交数量、价格、金额、佣金及 PnL；交易通知仅比较所记数据长度、时间、开平状态、方向、数量、价格、PnL 和净 PnL。未记录字段、其他策略和其他历史行情不在结论内。

## 开放边界

- 不等频第二数据源的子类仍有既存批量时钟差异：独立探针的逐根 marker 开始为 `136, 140, …`，基线和候选批量均为 `109, 110, …`；本轮没有解决该第二 Feed 投影。脚本 `D:/temp/i71_xperiod_independent_535e/subclass_multifeed_probe.py` SHA-256 `0a53be19e153f0c019972264f7ed89b0d476c675e935427c7029028f4b757660`。
- replay、动态数据结构或回调重入、完整 strict Inf/有限中间溢出、复杂自定义异常及完整输出事务语义均未全面验证；缺失输入的颜色消费风险仍需按消费者分别判断。
- 固定公开样本与合成数据只说明所测行为，不代表所有指标图、多 Feed、策略或真实账户能力。用户最终 `ACCEPTED` 未由本记录推定。

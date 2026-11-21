# B11-03：23 类指标的限定样本对照

本目录归档已完成且经独立复核的 R4 小样本，不是 B11-03 全项验收。公开源码基线为 Backtrader `c5fc2e7e954eae104d4acae5accdd9bf30e9c44d`；独立结论为 **GO_SAMPLE_ONLY**。本次归档没有重跑 Cerebro、比较器或历史测试。

## 样本和结果

使用 128 根连续合成 OHLCV、单 Feed、默认指标参数，Feed 显式为 Minutes/60，时间索引无时区。23 个大小写敏感的类身份及定义模块逐项匹配静态清单；其中 19 类在实际 `_runnext` 和 `_runonce` 调度下，所列全部公开线逐槽一致；EnvelopesJpAlonso 和 F2aAOIndicator 分别需要 200、164 根，输入不足；FisherOrgV1Sign 的 buy 线及 ForceDiverSign 的两条线在成熟期全非有限，结论不足。两个输入不足的类在调度前退出，未观察其输出。除这 23 类外，另有一个短历史分类控制和一个未审核类控制，不计入 19/2/2。

21 个完成运行的类共 39 条公开线，每线比较 128 槽，浮点比较使用 `rel_tol=1e-10`、`abs_tol=1e-12`，不是逐位相等。结果 JSON 保存两侧全部数值、类/模块、时钟、最小周期和每线非零计数。19 类在两种模式下的最小周期一致，但本轮没有独立的公式或最小周期期望。实际调度分支不同，不证明每个指标自己的 `once` 方法都被调用。

非零计数不能证明信号分支已触发：DarvasBoxesSystem 的 color 线成熟期 119 槽全部为 2.0。全非有限线可能表示合法无信号，也可能暴露问题，须按指标合同另验。本轮没有证明其他参数、缺失及恢复、多 Feed、异步时钟、时区转换、交易日、replay、真实账户或完整发行包行为。

## 执行和边界

实际运行器 `run_frozen_r4.py` 在执行前后核对冻结驱动、验证脚本和静态筛选脚本的 SHA-256，并核对受限 Git 快照全部 172 个公开文件；结果和收据逐字节保留。23 个指标各模式分别在有界超时子进程中执行；未知类、短历史和异常保留独立分类。每个完成样本记录了排除导入、目录外读取和模拟网络审计三项自检；没有额外拒绝。Python 导入拦截和审计钩子不是操作系统级沙箱，解释器前缀仍可读，部分启动发生在钩子安装之前。

为了避开不在范围内的交易接入组件及 contrib 包全量自动导入，运行时使用 light 入口以及 stores、observers、sizers、contrib 合成包壳，并单独注入 FixedSize；仍使用真实 Cerebro、模拟 BackBroker 和 PandasData。这是受限装配的样本证据，不代表默认完整包导入通过。`backtrader/_cerebro/execution.py` 是实际引擎调度文件，不是被排除的 SDK execution 包。

原 R3 探索版本将类名转小写，导致 ForceIndexEMA 与 ForceIndexEma 碰撞；该轮不纳入计数。本 R4 保留大小写，运行器把 23 条结果与静态清单的 class/module/ID 一对一核对。独立复核重新计算了 21 个已运行类的 39 条公开线和分类，见原始审阅文件。

## 来源重建

源树可从上述 Git 对象按 `verify_snapshot_r3.py` 中的明确路径集合导出；其中 172 个文件的运行前后 Git archive SHA-256 均为 `a16073aec698250c6c7db0a5ec047efe1704dc4be4f6e6486482ae7f051d2b87`。校验脚本比较路径集合和各文件原字节，不要求其他工作树内容。打包或运行新实验时，应使用新隔离目录、记录解释器和依赖，保留本目录不变。

原样归档的脚本包含原临时目录及 Git checkout 的绝对路径，并会创建固定输出；静态筛选脚本还引用原临时矩阵。它们是实际执行和静态筛选的原始凭据，不应直接在历史目录重跑或覆盖已有结果。如未来进行新实验，须将这些路径显式改为新的隔离位置，另命名脚本和结果、重新固定哈希；可使用本目录原始 `matrix.json` 复核静态筛选输入。原样结果、收据及独立审阅不得因重建改写。

## 原字节清单

以下文件逐字节复制自公开临时证据；本表不包含本说明及属性文件。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| run_frozen_r4.py | 3751 | `034749bd4512a836d3034172f2a382a37e29b02bdf862ed857138863c9dc4b36` |
| parity_harness_frozen_r4.py | 24742 | `2f128a288b4b3544f66cd3d1e1278a11d25fa3282507ec902bca656cd0733dfa` |
| verify_snapshot_r3.py | 2568 | `9d2b735b36609ad0b6e77af5a58dceebaf91f3b4161bef1a6c53319873d10b26` |
| static_review_r3.py | 4614 | `52ea6cf31ae3ac7ebccb05d2f6c1562b671a6176f562d1c97c65ec70a80e9928` |
| test_comparison_frozen_r4.py | 2828 | `2eab06c7706a290f10ac74b0ea0cf09fc7f42131524caaeb99683ebeef8788ab` |
| static_review_attested_r4_20261122.json | 10419 | `6180a7c2763fb5274750986dfb0041e8c63a993fcc867feb58aaeaa8856c2620` |
| expanded_attested_r4_20261122.json | 426201 | `2a1f366d98377a07d9fec2593d3ad0ba8d7c2f924a4c4a9b5584afe490cb4e99` |
| expanded_attested_r4_receipt_20261122.json | 3439 | `957265057535c0774c1f0489bccfcda7e1ca201a4c654782ddb3aad6ece4bc69` |
| independent_review_r4_20261122.md | 4584 | `d9727d504bc20a0c0f89d27f3482e76402e30b6694ef11717dd43492fff5209d` |
| matrix.json | 327088 | `715784c4666c55686f57284dfeb127734b2808f32deed0d1d2b24f0c08e0096e` |

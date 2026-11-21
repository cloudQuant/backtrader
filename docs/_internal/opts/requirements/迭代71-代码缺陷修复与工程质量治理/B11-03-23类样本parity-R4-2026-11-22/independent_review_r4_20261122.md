# B11-03 扩展 R4 试点独立复核（2026-11-22）

结论：**GO_SAMPLE_ONLY**。固定公开源码、受限包壳、单一合成数据和默认参数下，报告的19类具有两条 Cerebro 调度路径的所列公开线逐槽一致性；另2类输入不足、2类有全非有限公开线而结论不足，不能算完整指标通过。本复核没有重新执行已接受的 Cerebro 测试。

## 身份、来源和执行绑定

- 公开提交 `c5fc2e7e954eae104d4acae5accdd9bf30e9c44d`；冻结脚本 `parity_harness_frozen_r4.py` SHA-256 `2f128a288b4b3544f66cd3d1e1278a11d25fa3282507ec902bca656cd0733dfa`；结果 `expanded_attested_r4_20261122.json` SHA-256 `2a1f366d98377a07d9fec2593d3ad0ba8d7c2f924a4c4a9b5584afe490cb4e99`；执行收据 SHA-256 `957265057535c0774c1f0489bccfcda7e1ca201a4c654782ddb3aad6ece4bc69`。runner、static review、verify 和静态清单各自当前哈希均与收据相符；收据记录源码及脚本前后校验一致。
- 核对 R4 快照文件路径未包含 btapi/Gateway/SDK execution 等被排除路径后，只读运行来源验证：172个公开文件与固定 Git archive 的路径和字节一致，archive SHA-256 `a16073aec698250c6c7db0a5ec047efe1704dc4be4f6e6486482ae7f051d2b87`。`backtrader/_cerebro/execution.py` 为引擎生命周期文件，不是被排除的 SDK execution 包。独立重算树摘要 `4bf0dd9cdb06e249a44d0ad38861ccf7c10da186d0134db43db9b41003cbb79f` 与所有有树摘要的结果一致。
- 作者 R3 的小写 ID 碰撞结果不采用。R4 中 23 个 case ID、类名、模块路径与静态清单逐项一对一，区分 `ForceIndexEMA` 和 `ForceIndexEma` 及其不同源码模块；源码文件 SHA 与结果和静态清单逐项一致。

## 样本、数组和分类

21个完成构造和运行的类共39条公开线；我从每个类源码的 `lines` 字面声明核对报告线名，并对两侧每线128槽按报告容差独立重算，未见差异。19组标记 `parity_sample`，2组正确标记 `inconclusive_all_nonfinite`：FisherOrgV1Sign 的 buy 在成熟期112槽均为 NaN；ForceDiverSign 的 sell、buy 在成熟期各105槽均为 NaN。NaN 在这些指标中可能也是无信号表示，不据此宣称业务错误。

EnvelopesJpAlonso 与 F2aAOIndicator 在构造阶段分别声明200和164根，超过128根输入，两侧都标记 `insufficient_history`；构造提前退出，实际调度和输出均未观察，不能算通过。另一个独立 short-history 控制及未知类分别按 `insufficient_history` 和 `unsupported_unreviewed` 保留，不并入23类统计。

19组的两种已记录 minperiod 相等，但均未提供独立正确预期；无独立数值公式。`math.isclose` 使用 rel_tol=1e-10、abs_tol=1e-12，不是 bit 等价。DarvasBoxesSystem 唯一 color 线成熟期119槽全为常数2，虽然非零计数119，但并未证明状态转换或信号分支。其他非零线也不因此自动证明所有分支被激活。

## 时钟、护栏与扩展条件

21个完成运行的样本均记录 Cerebro 实际 `_runnext` / `_runonce` 分派；这不是每个指标自定义 once 必然被调用的证明。构造数据为 timezone-naive、连续128小时的确定性合成 OHLCV，单 feed，显式 `Minutes`（code 4）/compression 60。无交易日边界、时区转换、非同步多 Feed、replay、short/full history oracle 或缺失恢复场景。

stores、observers、sizers 与 contrib 的包入口用合成包壳，FixedSize 单独注入；只接受目标 contrib 模块，核心依赖并非逐模块完整白名单，不能当完整包导入验证。每个完成样本两侧的 excluded import、outside-read、network audit 三项合成自检为真且 denied 空；Python import finder 和 audit hook 不是 OS 级沙箱，且 sys.prefix/base_prefix 可读、部分解释器启动先于 hook。

R2 的不足分类提前掩盖 denied/required不一致问题在 R4 源码中已改为先核 denied，再校验两侧 required 类型、相等与大于可用长度；冻结测试文件列有相应纯比较器反例。未知类别和超时均不计通过。此批没有超时，不能以此推断扩展运行时长上界。

扩展仍应逐类审查依赖和数据合同，明确自然时间/会话类与状态/信号类；为每类单独补独立 minperiod、非平凡/非恒定信号、公式、缺失/恢复与所需回放。多种输出始终为NaN可能是合法无信号，也可能暴露异常，应结合指标合同单独判定，不通过更换样本掩盖。仅增加小样本 parity 不能关闭 B11-03。

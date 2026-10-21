# 迭代 45 Alpha101 覆盖清单

> **v0.9 状态同步附件｜2026-10-22**
> 本文件以101行登记公式的输入、算子族、截面/行业操作和能力依赖覆盖规划；它不是任一轮的全量因子库实现承诺或验收结果。R0已提交Alpha#3最小原生闭环；R3-S已提交静态依赖登记并通过3项测试，仅接受AC45-23静态登记部分。迭代45仍须由R1–R10完成当前native范围，其中R4以20个代表式手工核算H并验收真实Indicator执行；迭代46实现101/101 native；迭代47新增build编译前端并完成20式build/native等价；迭代48实现101/101 build和全量等价。45不编译DAG、不自动推导H、不实现build DSL。101行的逐公式能力验证仍为`NOT_RUN`，生产库状态为`NOT_IMPLEMENTED`；正式AC45尚未整体最终验收，组件结果不代表完整AC通过。

本清单是迭代45有效需求、设计和验收合同的覆盖附件，覆盖 REQ45-13..16、DS45-11..14、AC45-23..30。共同 grid/历史视图/缺格合同见[四迭代路线与对齐合同 ALN-01..08](./四迭代路线与对齐合同.md)。45 的全部公式统一以真实 `FactorIndicator(panel_mode="next")` 运行，算法根据公式定义处理时序、截面或行业语义；研究组各资产在进入 Cerebro 前按显式 grid 对齐为 BT-compatible 历史视图，缺格为 NaN、不沿用旧值，next-only 基线由 native owner/clock/minperiod 与 `once_via_next` 驱动，Strategy 只采集；手写原生 `once` 优化须证明与 `next` 在同一 grid 索引、输出和有效性语义上等价。manual H 由手工依赖窗口核算，Python 算法不编译 DAG/自动推 H。build/expression 前端是47新增能力。旧027 expression原型源码已从示例路径移除，仅可从Git历史追溯，历史类名为 `PanelFactorIndicator`；当前027是R0的真实 `FactorIndicator` native示例，不等同于47的build前端。AC45-23检查101项静态映射，R3-S已提交登记并通过3项测试，仅完成该AC的静态组件；完整AC45-23及AC45-24至AC45-30仍需各自正式证据。AC45-24检查数据/PIT，AC45-25检查45 native生命周期与grid调度，AC45-26检查算子，AC45-27检查因果和formula_universe隔离，AC45-28检查20个代表式，AC45-29检查安装产物上的native代表入口，AC45-30检查四迭代交接与边界。正式AC45尚未整体最终验收；四迭代均未完成全量因子库。公式结构依据 Kakushadze, *101 Formulaic Alphas*, Appendix A，尤其 A.1 的 Alpha#1–#101、A.2 的算子定义及 A.3 的输入定义：[官方 arXiv PDF](https://arxiv.org/pdf/1601.00991)。表格只归纳每条公式的结构与依赖，不重印公式全文；后续库实现须逐条以该附录原式为黄金语义，不能以本表的算子摘要替代。

AC45-23 的机器可审阅逐式静态登记见 [`backtrader/research/alpha101_dependencies.json`](../../../../../backtrader/research/alpha101_dependencies.json)：每个来源原式保留 token、标点及数值记法（仅将 PDF 提取后的换行和连续空白归一为单空格），并有摘要哈希；登记列明输入字段、调用与规范算子、比较/算术符号、数值常量、窗口及延迟参数、预热依赖类别、PIT 分类和 `formula_universe` 约束。登记按 TS 18、CS 65、industry 18 归组；这是依赖盘点，不是执行 DAG、精确 H、实现状态或验收结果。表中 #101 摘要继续保留原常数 `0.001`；登记另外保留论文原式中的 `.001` 记法。

## 1. 分类和记号

- 原始字段缩写：`O/H/L/C/V` 分别为 open/high/low/close/volume；`VWAP` 为成交量加权平均价。`(H+L)/2` 等组合字段由公式即时计算，不是新增市场输入。
- 派生/外部字段：`r` 为论文所定义的日 close-to-close returns；`advN` 为论文定义的过去 N 日平均日美元成交额；`cap` 为市值。`IndClass.level` 是行业分类映射。该登记不推定其原始供应方式、复权方式或 PIT 完备性。
- “截面操作”只登记普通截面 `rank` 与 `scale`；`Ts_Rank/ts_rank` 是时间序列排序，不计入截面 rank。alpha101-v1 将截面 `rank` 定义为平均秩除以截面资产数 `n`，`scale` 定义为绝对值和归一化。`IndNeutralize` 单列，并按每次调用计数。
- alpha101-v1 数值 profile：`SignedPower(x,a)=sign(x)×|x|^a`；移动标准差和协方差使用 `ddof=0`；所有公式窗口中的非整数长度按 `floor(d)` 转为整数；双表达式 `min(x,y)`/`max(x,y)` 按同一网格逐元素比较。论文同名的 `min(x,d)`/`max(x,d)` 时间序列窗口重载仍表示过去 d 期极值，不能误作双表达式算子。
- “代表依赖/边界”指出算子、窗口、分支或数值风险，不是完整依赖图，也不表示窗口/预热已经算出。本表当前为规划摘要。R3-S已逐式登记来源原式、静态字段、算子族、原始窗口常量及历史依赖类别；Root的3项测试通过，静态登记部分已接受。它不要求也不提供有序执行DAG或101式精确H；完整AC45-23及AC45-26仍须按验收方案独立验收。AC45-26另从原文独立核算全局算子集合并交叉核对，不能用摘要中未出现作为免测依据。输入来源和 `advN` 展开遵守 DS45-12；实施须按上述 alpha101-v1 profile 固定运算次序和边界。R4的20个native代表式需人工推导并独立复核 lookback H（含预热）；47 build 前端新增后才自动编译 H。
- “代表诊断配方”只为迭代45 R4 的可行性集成选择二十项：Alpha#1、#2、#3、#4、#7、#9、#13、#29、#48、#56、#58、#62、#63、#67、#81、#84、#92、#96、#100、#101。配方标签不表示这些公式已编码、运行或通过，也不表示对外发布了部分因子库。

## 2. Alpha#1–#101 结构登记

| ID | 直接字段 D / 派生输入 X | 截面 rank / scale | 行业层级 | 代表依赖算子或特别边界 | 迭代45诊断配方 | 迭代46/48库实现 | 迭代45能力验证 |
|---|---|---|---|---|---|---|---|
| #1 | D:C；X:r | rank | — | `stddev(20)`、`SignedPower`、`Ts_ArgMax(5)`、条件分支；argmax 并列位置 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #2 | D:O,C,V | rank | — | `log(V)`、`delta(2)`、`correlation(6)`；检查 log 与 O 分母定义域 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #3 | D:O,V | rank | — | `correlation(rank(O),rank(V),10)` | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #4 | D:L | rank | — | 截面 `rank(L)` 后 `Ts_Rank(9)`；不得把时间序列 rank 当截面 rank | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #5 | D:O,C,VWAP | rank | — | `sum(VWAP,10)`、绝对值与两处分支 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #6 | D:O,V | — | — | `correlation(O,V,10)`；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #7 | D:C,V；X:adv20 | — | — | `volume>adv20` 门控、`delta(C,7)`、`Ts_Rank(60)`、sign；保留门控常数分支 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #8 | D:O；X:r | rank | — | `sum(O,5)×sum(r,5)` 后 `delay(10)`；复合项延迟 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #9 | D:C | — | — | `delta(1)`、`ts_min/ts_max(5)` 与嵌套条件分支 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #10 | D:C | rank | — | `delta(1)`、`ts_min/ts_max(4)` 与嵌套条件分支 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #11 | D:C,V,VWAP | rank | — | `ts_max/ts_min(3)`、`delta(V,3)`；多个截面 rank 相乘 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #12 | D:C,V | — | — | `sign(delta(V,1))×delta(C,1)`；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #13 | D:C,V | rank | — | `covariance(rank(C),rank(V),5)` | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #14 | D:O,V；X:r | rank | — | `delta(r,3)` 与 `correlation(O,V,10)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #15 | D:H,V | rank | — | `correlation(rank(H),rank(V),3)` 后 `sum(3)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #16 | D:H,V | rank | — | `covariance(rank(H),rank(V),5)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #17 | D:C,V；X:adv20 | rank | — | `Ts_Rank(C,10)`、二阶差分、`Ts_Rank(V/adv20,5)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #18 | D:O,C | rank | — | `stddev(abs(C−O),5)` 与 `correlation(C,O,10)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #19 | D:C；X:r | rank | — | `delay/delta(C,7)`、`sum(r,250)`、sign | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #20 | D:O,H,L,C | rank | — | O 与前一 bar H/C/L 的三个独立 gap rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #21 | D:C,V；X:adv20 | — | — | 均值窗 8/2、`stddev(C,8)`、成交量/adv20 条件；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #22 | D:H,C,V | rank | — | `delta(correlation(H,V,5),5)` 与 `rank(stddev(C,20))` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #23 | D:H | — | — | `sum(H,20)/20` 条件比较及 `delta(H,2)`；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #24 | D:C | — | — | 均值窗 100、外层 `delta(100)`、`delay(C,100)`、`ts_min(C,100)` 与阈值分支；检查零分母 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #25 | D:H,C,VWAP；X:r,adv20 | rank | — | returns、adv20、VWAP、(H−C) 的乘积 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #26 | D:H,V | — | — | `correlation(Ts_Rank(V,5),Ts_Rank(H,5),5)` 后 `ts_max(3)`；两路分别排序，不是对 V/H 比值排序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #27 | D:V,VWAP | rank | — | 两层截面 rank、相关窗 6、时间求和窗 2 与阈值分支 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #28 | D:H,L,C；X:adv20 | scale | — | `correlation(adv20,L,5)` 加中点价差；L1 scale | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #29 | D:C；X:r | rank+scale | — | 嵌套 rank/scale、log、`ts_min`、sum/product、`min(x,5)` 时间窗重载与延迟收益；检查 log/product 定义域 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #30 | D:C,V | rank | — | 连续 4 个 close 的 sign、`sum(V,5)/sum(V,20)`；时间序列成交量比 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #31 | D:L,C；X:adv20 | rank+scale | — | `delta(C,10)` 多层 rank、`decay_linear(10)`、相关窗 12 与 scale | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #32 | D:C,VWAP | scale | — | `sum(C,7)/7−C` 与 `correlation(VWAP,delay(C,5),230)` 分别 scale | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #33 | D:O,C | rank | — | O/C 比值的幂 1；检查 close 为零时的除法 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #34 | D:C；X:r | rank | — | `stddev(r,2)/stddev(r,5)`、`delta(C,1)` 与嵌套 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #35 | D:H,L,C,V；X:r | — | — | `Ts_Rank(V,32)`、价格范围项窗 16、`Ts_Rank(r,32)`；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #36 | D:O,C,V,VWAP；X:r,adv20 | rank | — | 多个加权 rank、延迟 V/r、相关窗 15/6、`sum(C,200)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #37 | D:O,C | rank | — | `correlation(delay(O−C,1),C,200)` 与截面价差 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #38 | D:O,C | rank | — | `Ts_Rank(C,10)` 与 C/O；检查开盘为零 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #39 | D:C,V；X:r,adv20 | rank | — | `delta(C,7)`、`decay_linear(V/adv20,9)`、`sum(r,250)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #40 | D:H,V | rank | — | `stddev(H,10)` 与 `correlation(H,V,10)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #41 | D:H,L,VWAP | — | — | `sqrt(H×L)−VWAP`；平方根定义域；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #42 | D:C,VWAP | rank | — | 两个截面 rank 的比值；属于 delay-0。按 `rank=r/n` 且非空截面时 rank 为正，分母不会为零；不得误用 `[-1,1]` 中心化 rank 制造零分母 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #43 | D:C,V；X:adv20 | — | — | `Ts_Rank(V/adv20,20)×Ts_Rank(−delta(C,7),8)`；`Ts_Rank` 不等于截面 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #44 | D:H,V | rank | — | `correlation(H,rank(V),5)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #45 | D:C,V | rank | — | `delay(C,5)`、求和窗 20、相关窗 2 的嵌套结构 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #46 | D:C | — | — | delay 20/10 的差分斜率、阈值 0.25/0 分支及 `delta(C,1)`；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #47 | D:H,C,V,VWAP；X:adv20 | rank | — | `1/C`、成交量/adv20、均值窗 5 与多重比值；检查分母 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #48 | D:C | — | subindustry ×1 | `delta(C,1)` 与延迟差分、相关窗 250、平方收益和；论文列为 delay-0 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #49 | D:C | — | — | 与 #46 同类的 delay 20/10 斜率、−0.1 阈值及 `delta(C,1)`；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #50 | D:V,VWAP | rank | — | `ts_max(5)`；内部相关基于两项截面 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #51 | D:C | — | — | delay 20/10 斜率、−0.05 阈值及 `delta(C,1)`；纯时序 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #52 | D:L,V；X:r | rank | — | `ts_min(L,5)` 延迟 5、240/20 收益和、`Ts_Rank(V,5)` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #53 | D:H,L,C | — | — | 价位比值的 `delta(9)`；分母 `C−L`；论文列为 delay-0 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #54 | D:O,H,L,C | — | — | 五次幂与比值；分母含 `L−H`；论文列为 delay-0 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #55 | D:H,L,C,V | rank | — | H/L 极值窗 12、归一化价位区间、相关窗 6；检查零振幅区间 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #56 | D:—；X:r,cap | rank | — | 收益嵌套求和、`rank(r×cap)`；cap 必须是时点可用的市值 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #57 | D:C,VWAP | rank | — | `Ts_ArgMax(C,30)`、`decay_linear(2)` 作为分母；检查零分母 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #58 | D:V,VWAP | — | sector ×1 | VWAP 行业中性化后 `correlation(3.92795)`、线性衰减(7.89291)、`Ts_Rank(5.50322)`；非整数窗取 floor | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #59 | D:V,VWAP | — | industry ×1 | 加权的两项均为 VWAP；保留原式结构；中性化、相关/衰减/时序 rank 的非整数窗 floor | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #60 | D:H,L,C,V | rank+scale | — | 价位区间分子/`H−L`、`Ts_ArgMax(C,10)`；两处 scale；检查零区间与零 scale 范数 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #61 | D:VWAP；X:adv180 | rank | — | `ts_min(VWAP,16.1219)` 与相关窗 17.9282 的 rank 比较；非整数窗 floor | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #62 | D:O,H,L,VWAP；X:adv20 | rank | — | 对相关、均值窗 22.4101 和嵌套比较分别 rank；比较结果为布尔量 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #63 | D:O,C,VWAP；X:adv180 | rank | industry ×1 | 行业中性化 close 后 delta/衰减；相关加权价与 `sum(adv180,37.2467)` | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #64 | D:O,H,L,VWAP；X:adv120 | rank | — | 加权 O/L 求和窗 12.7054、adv120 求和、相关与加权价差 delta | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #65 | D:O,VWAP；X:adv60 | rank | — | 加权 O/VWAP、adv60 求和、相关窗 6.40374；与开盘相对 ts_min 比较 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #66 | D:O,H,L,VWAP | rank | — | VWAP delta/衰减；加权 low（两项同为 low）与 `(O−中点)` 分母；保留原式 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #67 | D:H,VWAP；X:adv20 | rank | sector ×1; subindustry ×1 | `IndNeutralize` 两次且层级不同；相关窗 6.02936 作幂指数 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #68 | D:H,L,C；X:adv15 | rank | — | rank 后相关窗 8.91644/时序 rank；加权 C/L 的 delta 与比较 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #69 | D:C,VWAP；X:adv20 | rank | industry ×1 | 中性化 VWAP 的 delta/`ts_max`，以及带时序 rank 的相关/幂 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #70 | D:C,VWAP；X:adv50 | rank | industry ×1 | delta VWAP；行业中性化 close 后相关窗 17.8256 与 `Ts_Rank` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #71 | D:O,L,C,VWAP；X:adv180 | rank | — | 两路嵌套 `Ts_Rank`/衰减/相关；双表达式逐元素 `max`，并列按算子合同 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #72 | D:H,L,V,VWAP；X:adv40 | rank | — | 两路衰减相关；分母含截面 rank；检查零分母 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #73 | D:O,L,VWAP | rank | — | VWAP delta/衰减与加权 O/L 收益率的衰减、`Ts_Rank`；双表达式逐元素 `max` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #74 | D:H,C,VWAP,V；X:adv30 | rank | — | 两路相关与截面比较；含加权 H/VWAP 和 rank(V) | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #75 | D:L,V,VWAP；X:adv50 | rank | — | rank(correlation) 两路比较，其中一路输入先截面 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #76 | D:L,VWAP；X:adv81 | rank | sector ×1 | max 两路；一支为 delta/衰减，另一支为 sector 中性化相关的多层时序运算 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #77 | D:H,L,VWAP；X:adv40 | rank | — | 两路 `decay_linear` 后逐元素取双表达式 `min`；一支为相关窗 3.1614 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #78 | D:L,V,VWAP；X:adv40 | rank | — | 两个截面 rank correlation 的幂；求和窗 19.7428 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #79 | D:O,C,VWAP；X:adv150 | rank | sector ×1 | 加权 O/C 经 sector 中性化后 delta；与两路时序 rank 相关比较 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #80 | D:O,H；X:adv10 | rank | industry ×1 | 加权 O/H 中性化、delta/sign；相关结果参与幂指数 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #81 | D:V,VWAP；X:adv10 | rank | — | `product(14.9655)`、log 及幂 4；检查 log/product 定义域 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #82 | D:O,V | rank | sector ×1 | 双表达式逐元素 `min`；一支含 sector 中性化 V 与加权 O 的相关、衰减/时序 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #83 | D:H,L,C,V,VWAP | rank | — | 区间/均值和 VWAP−C 多重比值；`delay(2)`；检查零分母 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #84 | D:C,VWAP | — | — | `Ts_Rank` 的 `SignedPower`，指数为 `delta(C,4.96796)`；纯时序 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #85 | D:H,L,C,V；X:adv30 | rank | — | 两路 rank-correlation 复合幂；内部两路 `Ts_Rank` | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #86 | D:O,C,VWAP；X:adv20 | rank | — | `Ts_Rank(correlation(C,sum(adv20,14.7444),6),20.4195)` 与截面阈值比较 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #87 | D:C,VWAP；X:adv81 | rank | industry ×1 | 加权价 delta/衰减与 industry-neutralize adv81 后绝对相关/衰减 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #88 | D:O,H,L,C；X:adv60 | rank | — | 两路取逐元素双表达式 `min`；嵌套 rank、时序 rank、相关与多层衰减 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #89 | D:L,VWAP；X:adv10 | — | industry ×1 | `Ts_Rank` 两路之差；一支以 industry-neutralize VWAP 做 delta；无普通 rank/scale | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #90 | D:L,C；X:adv40 | rank | subindustry ×1 | rank(close−`ts_max`) 的幂；指数含中性化 adv40 的时序相关 rank | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #91 | D:C,V,VWAP；X:adv30 | rank | industry ×1 | 中性化 close 的相关经两层衰减和 `Ts_Rank`；减去另一 rank/衰减项 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #92 | D:O,H,L,C；X:adv30 | rank | — | 双表达式逐元素 `min`；第二路明确包含 `rank(L)`、`rank(adv30)` 后相关，非纯时序 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #93 | D:C,VWAP；X:adv81 | rank | industry ×1 | 中性化 VWAP 的相关/衰减/时序 rank 除以另一 rank/衰减项 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #94 | D:VWAP；X:adv60 | rank | — | 截面 rank 作幂底；指数为两路时序 rank 相关 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #95 | D:O,H,L；X:adv40 | rank | — | `Ts_Rank` 外层包含截面 rank、相关和五次幂；比较结果为布尔量 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #96 | D:C,V,VWAP；X:adv60 | rank | — | max 两路；含 `Ts_ArgMax`、多层时序 rank/衰减/相关 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #97 | D:L,VWAP；X:adv60 | rank | industry ×1 | 加权 L/VWAP 中性化后 delta/衰减；另一支为多层时序 rank/相关 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #98 | D:O,VWAP；X:adv5,adv15 | rank | — | 两路 rank/衰减之差；含 `Ts_ArgMin` 和相关嵌套 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #99 | D:H,L,V；X:adv60 | rank | — | 两路相关的截面 rank 比较；一支使用中点和 adv60 求和 | — | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #100 | D:H,L,C,V；X:adv20 | rank+scale | subindustry ×3 | 按原顺序三次 subindustry 中性化、两次 scale、`Ts_ArgMin(30)`；检查 H−L 与 adv20 分母 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |
| #101 | D:O,H,L,C | — | — | `(C−O)/(H−L+0.001)`；常数只规避零振幅分母，不得删改；纯时序 | R4 代表可行性诊断配方 | 迭代46 native / 迭代48 build / NOT_IMPLEMENTED | NOT_RUN |

## 3. 覆盖计数与迭代45能力路线

### 3.1 公式结构计数

下列分类仅描述论文公式的结构，供能力规划和风险覆盖使用；它们不是迭代45实现分组或验收承诺。

| 类别 | 数量 | ID / 说明 |
|---|---:|---|
| 无任何截面操作 | 18 | #6, #7, #9, #12, #21, #23, #24, #26, #35, #41, #43, #46, #49, #51, #53, #54, #84, #101 |
| 有截面操作但不含行业中性化 | 65 | 101 − 18 个无截面操作 − 18 个含行业中性化 |
| 含行业中性化 | 18 | #48, #58, #59, #63, #67, #69, #70, #76, #79, #80, #82, #87, #89, #90, #91, #93, #97, #100 |
| 普通截面 `rank` | 77 | 按公式 ID 计；不计 `Ts_Rank` |
| 截面 `scale` | 6 | #28, #29, #31, #32, #60, #100；#31/#60/#100 也含 `rank`。#29 按 Appendix A 原式计入 `scale` |
| `IndNeutralize` 调用总数 | 21 | #67 两次；#100 三次；其余 16 个行业公式各一次 |
| delay-0 公式 | 4 | #42, #48, #53, #54；依论文定义，拟在同一交易日收盘或尽可能接近收盘时使用 |

行业调用按论文公式出现次数计数：sector 5 次，industry 10 次，subindustry 6 次。#67 同一 Alpha 同时使用 sector 与 subindustry；#100 共出现三次 subindustry 中性化，顺序不可因同层级而折叠。论文也指出同一公式中的 `IndClass` 不保证使用同一分类体系。特别地，#56 的输入包含 `cap`；#92 同时包含 `rank(low)` 与 `rank(adv30)`，因此不是纯时序公式。这里的计数用于静态映射；字段来源、时点可用性和派生展开仍由 DS45-12 约束。

### 3.2 四迭代能力路线

| 轮次 | 能力/边界 |
|---|---|
| R0 | 已提交并完成 Alpha#3 最小原生端到端闭环展示；证据为SOURCE_NATIVE_CEREBRO_R0_ONLY，不替代完整AC或R1–R10完成判定 |
| R1 | FactorIndicator 统一采集合同；按原文补齐101式完整静态输入/算子族/窗口登记 |
| R2 | 复用真实 BT FactorIndicator/Lines/owner/clock/minperiod/`once_via_next` 和同步视图；只在实证原生缺口时引入最小 adapter |
| R3 | 算子与PIT数据能力；依DS45-12/13/14固定语义、输入和复现边界 |
| R3-S | 已提交101项静态依赖登记JSON（d9c6a631）；Root测试3 passed，仅接受AC45-23静态登记部分，不代表完整AC45-23或公式执行验收 |
| R4 | 以独立oracle验收原生next的20个代表式（#1、#2、#3、#4、#7、#9、#13、#29、#48、#56、#58、#62、#63、#67、#81、#84、#92、#96、#100、#101），人工核算H；不形成公开全量库 |
| R5 | fincore 标签 |
| R6 | 合成比较 |
| R7 | 统计 |
| R8 | 保存、导出、安装；关闭 AC45-29：20个 native 代表式及 fincore 已安装产物验收 |
| R9 | 单例示例 025 |
| R10 | 多因子示例 026；关闭 AC45-20/30 的组合能力与四迭代交接验收 |
| L0–L4 | 迭代46：L0生产提升最小闭环，随后交付全101 native台账、81式新增、101/101全量回归和安装集成 |
| E1–E5 | 迭代47：新增build编译前端和自动H、相关算子增强、20式build/native等价及对应安装集成 |
| B1–B3 | 迭代48：全101 build台账、81式新增、101/101 build与101/101 native/build等价 |

R0与R3-S已有受限组件验收；R1–R10其余工作及正式AC45整体结论仍待完成。R4的二十个代表配方用于验收研究和诊断能力，不是生产因子库或对外发布入口；20个native式仍为WIP。全101个公式的生产native库由迭代46实现，build库由迭代48实现，当前均为NOT_IMPLEMENTED；不把静态登记或代表配方结果表述成生产库覆盖。

### 3.3 迭代46/48实现前的技术门槛

以下是迭代46 native 与迭代47/48 build 逐个生产公式的实施与验收任务，不是迭代45开工前就必须交付的101套测试，也不是迭代45已完成的工作；迭代45只对20个代表配方执行原生数值验收：

1. 对每个 Alpha ID 建立独立于候选实现的逐条参考值/黄金用例，来源可为手工展开的小型输入或独立实现；不得只把候选函数重复调用作为预期值。用例需覆盖公式有效路径，并针对表中标出的分支、零分母、极值、常数或定义域边界断言行为。
2. 迭代46 native 公式显式记录并独立核算输入历史需求、复合 rolling 传播和预热 H，将 `advN` 自身窗口与非整数窗 floor 纳入逐式审查。本表未计算、也不声称已验收任何公式 lookback。自动构建依赖和推导 H 属迭代47 build 编译前端新增能力，迭代48沿用并验全量 build。
3. 对全 101 条逐一验证逐时流式结果与批量结果在相同索引上一致；按资产标识重排输入行后，逐资产结果保持一致，并遵守设计文档的 rank 并列合同。
4. 对每个时点 t，扰动 t 之后的行情、returns、adv、cap 或行业标签，不得改变 Alpha 在 t 及之前的输出；字段available_at晚于当前grid时，按DS45-12标NOT_YET_AVAILABLE，不得读取该值；缺失时间元数据则拒绝输入，不能由公式单测豁免。
5. 全量库实现不得使用 NaN 占位、skip、预期失败标记或部分实现来报告 Alpha101 全量覆盖。只有设计明确定义的预热缺失、源输入缺失或非法域行为可产生相应缺失/失败；NaN 不得伪装成未实现结果。

### 3.4 AC45-23..30 映射

| 验收项 | 本附件对应内容 | 当前状态 |
|---|---|---|
| AC45-23 | 本表 101 项静态输入/结构映射与计数 | NOT_RUN（R3-S静态登记组件已验收；完整AC45-23未最终验收） |
| AC45-24 | 完整字段、派生输入及 PIT 数据合同（DS45-12） | NOT_RUN |
| AC45-25 | 45 native FactorIndicator 的真实Indicator生命周期、显式grid调度及人工H独立核对 | NOT_RUN |
| AC45-26 | alpha101-v1 算子语义和边界（DS45-13） | NOT_RUN |
| AC45-27 | 因果模式与未来扰动能力 | NOT_RUN |
| AC45-28 | 二十个代表式可行性诊断配方 | NOT_RUN |
| AC45-29 | R8：45 native 20式代表入口及fincore接口的已安装产物验收 | NOT_RUN |
| AC45-30 | 四迭代交接和边界；迭代45不编全量库，迭代46/48分别验101/101 native/build | NOT_RUN |

## 4. 交付状态

本附件建立101项能力/依赖覆盖基线，并区分45 native闭环与后续全量库/build实现。R0已完成并通过限定范围的#3原生闭环；R3-S已完成静态依赖登记并仅验收AC45-23静态组件。R1–R10其余工作、正式AC45最终结论、迭代46 L0–L4、迭代47 E1–E5和迭代48 B1–B3仍待相应验收。Alpha#1–#101逐公式能力验证均为`NOT_RUN`，生产库实现均为`NOT_IMPLEMENTED`；不因此声明任何公式已受完整生产支持。20个native式仍为WIP。全量Alpha101 native由迭代46实现，全量build由迭代48实现；20式build及自动H由迭代47新增验收。当前027 expression原型源码已从示例路径移除，仅可从Git历史追溯，历史类名为`PanelFactorIndicator`；当前027是R0真实`FactorIndicator` native示例，R0证据不等于完整AC45或生产库通过。

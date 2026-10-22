# Alpha101 覆盖与实现验收台账

> **v1.3｜2026-10-23**。复用迭代45的101行静态覆盖清单，分别登记当前native基线、build实现、独立参考、同引擎native/build配对和安装状态。不得将注册数量、历史诊断或单个状态列解释为全量完成。

当前native基线来自[45–46优化验收结果](../迭代45-46优化/验收结果.md)：全部101式的源码参考与边界、已提交wheel两引擎矩阵已通过，运行内核提交`c01638893e4bf42496f69d8a3cbb1355e3a1ee9c`。47 E2提交`fe06ad468695b9cda675efd3ca09beade44a656e`增加四公式前端；其中只有Alpha003属于生产Alpha目录。47进一步运行全101 native长历史/字段/反事实检查，119项通过；[47记录](../迭代47-因子build简洁模式与算子增强/开发与验收记录.md)保留准确范围。47完整500资产和ff486565新wheel验收均通过，详见[47验收结果](../迭代47-因子build简洁模式与算子增强/验收结果.md)；48以该已验收提交继续补齐100式。

历史45的20个R4/R8诊断配方、旧wheel与离线复评是独立检查点，保留在最后一列及[代表验收案例](Alpha101代表验收案例.md)、[45验收结果](验收结果.md)、[旧离线复评归档](evidence/iteration45-offline-20261022/README.md)。这些历史实现及ResearchDataset/PIT接口已经删除，历史PASS不替代当前生产类验收。

唯一测试侧公式目录为[`tests/fixtures/research/alpha101_dependencies.json`](../../../../../tests/fixtures/research/alpha101_dependencies.json)；生产原式、字段和H直接由`alpha001.py`至`alpha101.py`类声明。该JSON不随运行包安装，也不作为第二套计算实现。公式结构来源仍为原清单引用的Kakushadze, *101 Formulaic Alphas*, Appendix A；本轮复用既有静态登记，不重新解释原式。

## 1. 记号与当前合同

- O/H/L/C/V为open/high/low/close/volume；VWAP、cap、ADV和行业编码须来自显式绑定或已有明确派生。表内D/X保留原静态依赖记号，不代表恢复独立PIT输入系统。
- 当前运行profile为`alpha101-v2`、float64。相关/协方差复用稳定核，rank按实际float精确并列；窗口小数取floor，滚动全窗、arg并列位置及三值布尔保持现有规则。
- H列是当前native类声明的历史格数，build必须与之及独立历史跨度一致。47/48均保留显式H，不自动推导；ADV预热、缺bar和研究窗口需在测试中独立核对。
- “双引擎配对”要求runnext、runonce各自的native/build完整逐格精确配对，包括mask、reason和离散分支；不能只拿两种实现分别通过容差oracle替代。
- 源码、安装、下游分别记录。48-B3覆盖全101的T320/T640/T1280四路源码矩阵；48-B4为583c2137新wheel的全101 T320四路矩阵。下游12表、101对实际报告及不可计算原因一致，详见[48验收结果](../迭代48-Alpha101-build实现/验收结果.md)。
- 完整退出条件见[共同合同](四迭代路线与对齐合同.md)、[47计划](../迭代47-因子build简洁模式与算子增强/迭代计划.md)与[48计划](../迭代48-Alpha101-build实现/迭代计划.md)。

## 2. 101个唯一公式ID

| ID | 直接字段D / 派生输入X | 截面rank / scale | 行业层级 | 代表依赖算子或特别边界 | 迭代45诊断配方 | 显式H | native基线 | build实现 | build独立参考 | build双引擎配对 | build安装 | 迭代45历史诊断 |
|---|---|---|---|---|---|---:|---|---|---|---|---|---|
| #1 | D:C；X:r | rank | — | `stddev(20)`、`SignedPower`、`Ts_ArgMax(5)`、条件分支；argmax 并列位置 | R4 代表可行性诊断配方 | 24 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #2 | D:O,C,V | rank | — | `log(V)`、`delta(2)`、`correlation(6)`；检查 log 与 O 分母定义域 | R4 代表可行性诊断配方 | 7 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #3 | D:O,V | rank | — | `correlation(rank(O),rank(V),10)` | R4 代表可行性诊断配方 | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #4 | D:L | rank | — | 截面 `rank(L)` 后 `Ts_Rank(9)`；不得把时间序列 rank 当截面 rank | R4 代表可行性诊断配方 | 8 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #5 | D:O,C,VWAP | rank | — | `sum(VWAP,10)`、绝对值与两处分支 rank | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #6 | D:O,V | — | — | `correlation(O,V,10)`；纯时序 | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #7 | D:C,V；X:adv20 | — | — | `volume>adv20` 门控、`delta(C,7)`、`Ts_Rank(60)`、sign；保留门控常数分支 | R4 代表可行性诊断配方 | 66 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #8 | D:O；X:r | rank | — | `sum(O,5)×sum(r,5)` 后 `delay(10)`；复合项延迟 | — | 15 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #9 | D:C | — | — | `delta(1)`、`ts_min/ts_max(5)` 与嵌套条件分支 | R4 代表可行性诊断配方 | 5 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #10 | D:C | rank | — | `delta(1)`、`ts_min/ts_max(4)` 与嵌套条件分支 | — | 4 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #11 | D:C,V,VWAP | rank | — | `ts_max/ts_min(3)`、`delta(V,3)`；多个截面 rank 相乘 | — | 3 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #12 | D:C,V | — | — | `sign(delta(V,1))×delta(C,1)`；纯时序 | — | 1 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #13 | D:C,V | rank | — | `covariance(rank(C),rank(V),5)` | R4 代表可行性诊断配方 | 4 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #14 | D:O,V；X:r | rank | — | `delta(r,3)` 与 `correlation(O,V,10)` | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #15 | D:H,V | rank | — | `correlation(rank(H),rank(V),3)` 后 `sum(3)` | — | 4 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #16 | D:H,V | rank | — | `covariance(rank(H),rank(V),5)` | — | 4 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #17 | D:C,V；X:adv20 | rank | — | `Ts_Rank(C,10)`、二阶差分、`Ts_Rank(V/adv20,5)` | — | 23 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #18 | D:O,C | rank | — | `stddev(abs(C−O),5)` 与 `correlation(C,O,10)` | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #19 | D:C；X:r | rank | — | `delay/delta(C,7)`、`sum(r,250)`、sign | — | 250 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #20 | D:O,H,L,C | rank | — | O 与前一 bar H/C/L 的三个独立 gap rank | — | 1 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #21 | D:C,V；X:adv20 | — | — | 均值窗 8/2、`stddev(C,8)`、成交量/adv20 条件；纯时序 | — | 19 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #22 | D:H,C,V | rank | — | `delta(correlation(H,V,5),5)` 与 `rank(stddev(C,20))` | — | 19 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #23 | D:H | — | — | `sum(H,20)/20` 条件比较及 `delta(H,2)`；纯时序 | — | 19 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #24 | D:C | — | — | 均值窗 100、外层 `delta(100)`、`delay(C,100)`、`ts_min(C,100)` 与阈值分支；检查零分母 | — | 199 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #25 | D:H,C,VWAP；X:r,adv20 | rank | — | returns、adv20、VWAP、(H−C) 的乘积 | — | 19 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #26 | D:H,V | — | — | `correlation(Ts_Rank(V,5),Ts_Rank(H,5),5)` 后 `ts_max(3)`；两路分别排序，不是对 V/H 比值排序 | — | 10 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #27 | D:V,VWAP | rank | — | 两层截面 rank、相关窗 6、时间求和窗 2 与阈值分支 | — | 6 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #28 | D:H,L,C；X:adv20 | scale | — | `correlation(adv20,L,5)` 加中点价差；L1 scale | — | 23 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #29 | D:C；X:r | rank+scale | — | 嵌套 rank/scale、log、`ts_min`、sum/product、`min(x,5)` 时间窗重载与延迟收益；检查 log/product 定义域 | R4 代表可行性诊断配方 | 11 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #30 | D:C,V | rank | — | 连续 4 个 close 的 sign、`sum(V,5)/sum(V,20)`；时间序列成交量比 | — | 19 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #31 | D:L,C；X:adv20 | rank+scale | — | `delta(C,10)` 多层 rank、`decay_linear(10)`、相关窗 12 与 scale | — | 30 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #32 | D:C,VWAP | scale | — | `sum(C,7)/7−C` 与 `correlation(VWAP,delay(C,5),230)` 分别 scale | — | 234 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #33 | D:O,C | rank | — | O/C 比值的幂 1；检查 close 为零时的除法 | — | 0 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #34 | D:C；X:r | rank | — | `stddev(r,2)/stddev(r,5)`、`delta(C,1)` 与嵌套 rank | — | 5 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #35 | D:H,L,C,V；X:r | — | — | `Ts_Rank(V,32)`、价格范围项窗 16、`Ts_Rank(r,32)`；纯时序 | — | 32 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #36 | D:O,C,V,VWAP；X:r,adv20 | rank | — | 多个加权 rank、延迟 V/r、相关窗 15/6、`sum(C,200)` | — | 199 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #37 | D:O,C | rank | — | `correlation(delay(O−C,1),C,200)` 与截面价差 rank | — | 200 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #38 | D:O,C | rank | — | `Ts_Rank(C,10)` 与 C/O；检查开盘为零 | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #39 | D:C,V；X:r,adv20 | rank | — | `delta(C,7)`、`decay_linear(V/adv20,9)`、`sum(r,250)` | — | 250 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #40 | D:H,V | rank | — | `stddev(H,10)` 与 `correlation(H,V,10)` | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #41 | D:H,L,VWAP | — | — | `sqrt(H×L)−VWAP`；平方根定义域；纯时序 | — | 0 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #42 | D:C,VWAP | rank | — | 两个截面 rank 的比值；属于 delay-0。按 `rank=r/n` 且非空截面时 rank 为正，分母不会为零；不得误用 `[-1,1]` 中心化 rank 制造零分母 | — | 0 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #43 | D:C,V；X:adv20 | — | — | `Ts_Rank(V/adv20,20)×Ts_Rank(−delta(C,7),8)`；`Ts_Rank` 不等于截面 rank | — | 38 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #44 | D:H,V | rank | — | `correlation(H,rank(V),5)` | — | 4 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #45 | D:C,V | rank | — | `delay(C,5)`、求和窗 20、相关窗 2 的嵌套结构 | — | 24 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #46 | D:C | — | — | delay 20/10 的差分斜率、阈值 0.25/0 分支及 `delta(C,1)`；纯时序 | — | 20 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #47 | D:H,C,V,VWAP；X:adv20 | rank | — | `1/C`、成交量/adv20、均值窗 5 与多重比值；检查分母 | — | 19 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #48 | D:C | — | subindustry ×1 | `delta(C,1)` 与延迟差分、相关窗 250、平方收益和；论文列为 delay-0 | R4 代表可行性诊断配方 | 251 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #49 | D:C | — | — | 与 #46 同类的 delay 20/10 斜率、−0.1 阈值及 `delta(C,1)`；纯时序 | — | 20 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #50 | D:V,VWAP | rank | — | `ts_max(5)`；内部相关基于两项截面 rank | — | 8 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #51 | D:C | — | — | delay 20/10 斜率、−0.05 阈值及 `delta(C,1)`；纯时序 | — | 20 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #52 | D:L,V；X:r | rank | — | `ts_min(L,5)` 延迟 5、240/20 收益和、`Ts_Rank(V,5)` | — | 240 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #53 | D:H,L,C | — | — | 价位比值的 `delta(9)`；分母 `C−L`；论文列为 delay-0 | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #54 | D:O,H,L,C | — | — | 五次幂与比值；分母含 `L−H`；论文列为 delay-0 | — | 0 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #55 | D:H,L,C,V | rank | — | H/L 极值窗 12、归一化价位区间、相关窗 6；检查零振幅区间 | — | 16 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #56 | D:—；X:r,cap | rank | — | 收益嵌套求和、`rank(r×cap)`；cap 必须是时点可用的市值 | R4 代表可行性诊断配方 | 10 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #57 | D:C,VWAP | rank | — | `Ts_ArgMax(C,30)`、`decay_linear(2)` 作为分母；检查零分母 | — | 30 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #58 | D:V,VWAP | — | sector ×1 | VWAP 行业中性化后 `correlation(3.92795)`、线性衰减(7.89291)、`Ts_Rank(5.50322)`；非整数窗取 floor | R4 代表可行性诊断配方 | 12 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #59 | D:V,VWAP | — | industry ×1 | 加权的两项均为 VWAP；保留原式结构；中性化、相关/衰减/时序 rank 的非整数窗 floor | — | 25 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #60 | D:H,L,C,V | rank+scale | — | 价位区间分子/`H−L`、`Ts_ArgMax(C,10)`；两处 scale；检查零区间与零 scale 范数 | — | 9 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #61 | D:VWAP；X:adv180 | rank | — | `ts_min(VWAP,16.1219)` 与相关窗 17.9282 的 rank 比较；非整数窗 floor | — | 195 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #62 | D:O,H,L,VWAP；X:adv20 | rank | — | 对相关、均值窗 22.4101 和嵌套比较分别 rank；比较结果为布尔量 | R4 代表可行性诊断配方 | 48 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #63 | D:O,C,VWAP；X:adv180 | rank | industry ×1 | 行业中性化 close 后 delta/衰减；相关加权价与 `sum(adv180,37.2467)` | R4 代表可行性诊断配方 | 238 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #64 | D:O,H,L,VWAP；X:adv120 | rank | — | 加权 O/L 求和窗 12.7054、adv120 求和、相关与加权价差 delta | — | 145 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #65 | D:O,VWAP；X:adv60 | rank | — | 加权 O/VWAP、adv60 求和、相关窗 6.40374；与开盘相对 ts_min 比较 | — | 71 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #66 | D:O,H,L,VWAP | rank | — | VWAP delta/衰减；加权 low（两项同为 low）与 `(O−中点)` 分母；保留原式 | — | 15 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #67 | D:H,VWAP；X:adv20 | rank | sector ×1; subindustry ×1 | `IndNeutralize` 两次且层级不同；相关窗 6.02936 作幂指数 | R4 代表可行性诊断配方 | 24 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #68 | D:H,L,C；X:adv15 | rank | — | rank 后相关窗 8.91644/时序 rank；加权 C/L 的 delta 与比较 | — | 33 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #69 | D:C,VWAP；X:adv20 | rank | industry ×1 | 中性化 VWAP 的 delta/`ts_max`，以及带时序 rank 的相关/幂 | — | 30 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #70 | D:C,VWAP；X:adv50 | rank | industry ×1 | delta VWAP；行业中性化 close 后相关窗 17.8256 与 `Ts_Rank` | — | 81 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #71 | D:O,L,C,VWAP；X:adv180 | rank | — | 两路嵌套 `Ts_Rank`/衰减/相关；双表达式逐元素 `max`，并列按算子合同 | — | 224 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #72 | D:H,L,V,VWAP；X:adv40 | rank | — | 两路衰减相关；分母含截面 rank；检查零分母 | — | 55 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #73 | D:O,L,VWAP | rank | — | VWAP delta/衰减与加权 O/L 收益率的衰减、`Ts_Rank`；双表达式逐元素 `max` | — | 19 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #74 | D:H,C,VWAP,V；X:adv30 | rank | — | 两路相关与截面比较；含加权 H/VWAP 和 rank(V) | — | 79 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #75 | D:L,V,VWAP；X:adv50 | rank | — | rank(correlation) 两路比较，其中一路输入先截面 rank | — | 60 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #76 | D:L,VWAP；X:adv81 | rank | sector ×1 | max 两路；一支为 delta/衰减，另一支为 sector 中性化相关的多层时序运算 | — | 139 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #77 | D:H,L,VWAP；X:adv40 | rank | — | 两路 `decay_linear` 后逐元素取双表达式 `min`；一支为相关窗 3.1614 | — | 45 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #78 | D:L,V,VWAP；X:adv40 | rank | — | 两个截面 rank correlation 的幂；求和窗 19.7428 | — | 62 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #79 | D:O,C,VWAP；X:adv150 | rank | sector ×1 | 加权 O/C 经 sector 中性化后 delta；与两路时序 rank 相关比较 | — | 170 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #80 | D:O,H；X:adv10 | rank | industry ×1 | 加权 O/H 中性化、delta/sign；相关结果参与幂指数 | — | 17 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #81 | D:V,VWAP；X:adv10 | rank | — | `product(14.9655)`、log 及幂 4；检查 log/product 定义域 | R4 代表可行性诊断配方 | 77 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #82 | D:O,V | rank | sector ×1 | 双表达式逐元素 `min`；一支含 sector 中性化 V 与加权 O 的相关、衰减/时序 rank | — | 33 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #83 | D:H,L,C,V,VWAP | rank | — | 区间/均值和 VWAP−C 多重比值；`delay(2)`；检查零分母 | — | 6 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #84 | D:C,VWAP | — | — | `Ts_Rank` 的 `SignedPower`，指数为 `delta(C,4.96796)`；纯时序 | R4 代表可行性诊断配方 | 33 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #85 | D:H,L,C,V；X:adv30 | rank | — | 两路 rank-correlation 复合幂；内部两路 `Ts_Rank` | — | 37 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #86 | D:O,C,VWAP；X:adv20 | rank | — | `Ts_Rank(correlation(C,sum(adv20,14.7444),6),20.4195)` 与截面阈值比较 | — | 56 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #87 | D:C,VWAP；X:adv81 | rank | industry ×1 | 加权价 delta/衰减与 industry-neutralize adv81 后绝对相关/衰减 | — | 108 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #88 | D:O,H,L,C；X:adv60 | rank | — | 两路取逐元素双表达式 `min`；嵌套 rank、时序 rank、相关与多层衰减 | — | 91 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #89 | D:L,VWAP；X:adv10 | — | industry ×1 | `Ts_Rank` 两路之差；一支以 industry-neutralize VWAP 做 delta；无普通 rank/scale | — | 26 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #90 | D:L,C；X:adv40 | rank | subindustry ×1 | rank(close−`ts_max`) 的幂；指数含中性化 adv40 的时序相关 rank | — | 45 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #91 | D:C,V,VWAP；X:adv30 | rank | industry ×1 | 中性化 close 的相关经两层衰减和 `Ts_Rank`；减去另一 rank/衰减项 | — | 33 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #92 | D:O,H,L,C；X:adv30 | rank | — | 双表达式逐元素 `min`；第二路明确包含 `rank(L)`、`rank(adv30)` 后相关，非纯时序 | R4 代表可行性诊断配方 | 45 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #93 | D:C,VWAP；X:adv81 | rank | industry ×1 | 中性化 VWAP 的相关/衰减/时序 rank 除以另一 rank/衰减项 | — | 120 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #94 | D:VWAP；X:adv60 | rank | — | 截面 rank 作幂底；指数为两路时序 rank 相关 | — | 80 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #95 | D:O,H,L；X:adv40 | rank | — | `Ts_Rank` 外层包含截面 rank、相关和五次幂；比较结果为布尔量 | — | 78 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #96 | D:C,V,VWAP；X:adv60 | rank | — | max 两路；含 `Ts_ArgMax`、多层时序 rank/衰减/相关 | R4 代表可行性诊断配方 | 100 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #97 | D:L,VWAP；X:adv60 | rank | industry ×1 | 加权 L/VWAP 中性化后 delta/衰减；另一支为多层时序 rank/相关 | — | 114 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #98 | D:O,VWAP；X:adv5,adv15 | rank | — | 两路 rank/衰减之差；含 `Ts_ArgMin` 和相关嵌套 | — | 52 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #99 | D:H,L,V；X:adv60 | rank | — | 两路相关的截面 rank 比较；一支使用中点和 adv60 求和 | — | 84 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | NOT_RUN |
| #100 | D:H,L,C,V；X:adv20 | rank+scale | subindustry ×3 | 按原顺序三次 subindustry 中性化、两次 scale、`Ts_ArgMin(30)`；检查 H−L 与 adv20 分母 | R4 代表可行性诊断配方 | 29 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |
| #101 | D:O,H,L,C | — | — | `(C−O)/(H−L+0.001)`；常数只规避零振幅分母，不得删改；纯时序 | R4 代表可行性诊断配方 | 0 | PASS（OPT） | 已实现（48-B2） | PASS（48-B3,T320/640/1280） | PASS（48-B3,T320/640/1280） | PASS（48-B4,T320） | PASS（R4/R8诊断；非生产库） |

## 3. 公式结构计数（沿用静态清单）


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

行业调用按论文公式出现次数计数：sector 5 次，industry 10 次，subindustry 6 次。#67 同一 Alpha 同时使用 sector 与 subindustry；#100 共出现三次 subindustry 中性化，顺序不可因同层级而折叠。论文也指出同一公式中的 `IndClass` 不保证使用同一分类体系。特别地，#56 的输入包含 `cap`；#92 同时包含 `rank(low)` 与 `rank(adv30)`，因此不是纯时序公式。这里的计数用于静态映射；字段来源、时点可用性和单位由调用者保证；当前绑定与派生遵守重构后的普通feed合同。


## 4. 持续维护与验收要求

1. 48已补齐100个同文件伴随类。后续修改仍按实际通过的源码、独立参考、两引擎配对及安装分别维护；新提交尚未运行的检查保持NOT_RUN，不能继承旧候选的PASS。
2. 复用现有harness与独立AST参考，逐节点定位首个差异；比较全部资产/时点、reason和有限见证。不得裁剪NaN交集、排序整行或放宽rank/分支判断。
3. 资产重排覆盖完整时间范围，未来扰动核对完整历史前缀；行业、ADV、缺bar、平坦/零分母、混合装配和跨实例隔离均保留实际公共路径。字段的point-in-time正确性由源数据负责，不恢复available_at/as-of运行框架。
4. 已提交wheel必须仓外导入并保留准确源码、产物哈希、RECORD和依赖身份。复用Anaconda依赖不称为全新隔离环境；源码通过不自动更新安装列。
5. 48的全101下游数据/报告及三个示例回归已经通过；后续仍须保持这些检查。固定六资产fixture的14式不可三分位原因保留，不把配对PASS解释为所有指标均可计算。台账状态不代表收益、5,471只全年、实盘账户、发布或部署验收。

当前计数：native基线101/101 PASS；build实现101/101；三种历史长度的build独立参考与双引擎配对101/101；48新wheel安装101/101；下游完整结果/原因及报告配对101/101。准确提交、哈希、范围与固定fixture的PARTIAL评价状态见[48验收结果](../迭代48-Alpha101-build实现/验收结果.md)。

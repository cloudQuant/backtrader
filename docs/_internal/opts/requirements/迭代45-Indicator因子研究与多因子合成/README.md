# 迭代45–48因子研究文档入口

版本：**v0.9 状态同步稿**；更新：**2026-10-22**。R0 已提交并完成受限的 Alpha#3 原生闭环验收；R3-S 已提交 Alpha101 静态依赖登记，并只验收 AC45-23 的静态登记部分。正式 AC45-01..30 尚未整体完成最终验收，组件测试结果不代表完整 AC 通过。20 个 native 代表式仍处于 WIP，完整 101 个生产因子库仍为 **NOT_IMPLEMENTED**。历史 expression 原型与当前 native 示例的边界见下文。

## 1. 四个迭代的顺序与出口

| 迭代 | 交付目标 | 独立验收 |
|---|---|---|
| [45：原生能力与研究闭环](迭代计划.md) | R0已展示#3原生最小闭环；后续完成原生基础设施、20个代表配方、fincore、025单因子和026多因子示例 | AC45-01..30；R0通过不等于45完成 |
| [46：完整原生Alpha101](../迭代46-Alpha101原生因子实现/迭代计划.md) | 20个诊断配方提升为生产因子，再分批实现其余81式，完成101个原生因子 | AC46-01..06 |
| [47：build简洁模式](../迭代47-因子build简洁模式与算子增强/迭代计划.md) | 把build表达式编译到原生Indicator/Lines，补齐必要适配，完成20式三方对齐、混合使用和安装集成 | AC47-01..07 |
| [48：完整build Alpha101](../迭代48-Alpha101-build实现/迭代计划.md) | 完成101个build因子，逐式核对独立参考、native和build，验证完整安装入口 | AC48-01..06 |

顺序为45→46→47→48，每个迭代可按自身范围独立完成。旧稿把AC45的部分完成条件挂在47上，现已迁到对应AC47/48编号。两套完整因子库都为20+81=101，不重复计数。

## 2. 首先阅读的共同合同

[四迭代路线与对齐合同](四迭代路线与对齐合同.md)冻结原生优先规则和ALN-01..08对齐要求：

- 因子算法统一写在FactorIndicator中，FactorSpec不再提供execution选择，公共FactorStrategy负责装配、采集和封存；研究者不用为每个因子重写Strategy.next。
- 优先复用真实构造链、params、self.datas、Lines、owner/依赖注册、minperiod及Cerebro的next/once机制。单资产与截面因子均使用FactorIndicator，内部复用SMA/ROC等原生子指标；不预先要求专用owner或第二套数值引擎。
- R0已提交#3原生最小闭环：39项独立原生用例通过；与既有Indicator/SMA/ROC回归合并为42 passed。证据为SOURCE_NATIVE_CEREBRO_R0_ONLY，仅覆盖本轮范围，不关闭完整AC45。公共实现进入Backtrader安装包，示例只保留公式和运行装配。
- 47的build是简洁声明入口，编译为已验收原生算子和Lines；原生与build共享数学语义。build声明类无需实例化，但生成的Indicator节点仍须正常注册和调度。
- 原生、build都分别对照独立oracle，再比较彼此。完整索引、缺失位置、reason、首有效时点和离散结果精确一致；连续值默认按`abs(actual-expected) <= 1e-12 + 1e-10*abs(expected)`比较，阈值事先冻结。
- 还须覆盖资产重排、未来扰动、PIT、长预热、缺格、runonce/runnext、混合运行和安装产物。IC相近不能替代公式逐值对齐；全部NaN不能通过。

## 3. 当前有效资料

| 阅读顺序 | 文件 | 内容 |
|---|---|---|
| 1 | [共同合同](四迭代路线与对齐合同.md) | 四迭代边界、原生复用和跨后端对齐 |
| 2 | [需求文档](需求文档.md) | REQ45-01..16、用户入口与研究范围 |
| 3 | [设计文档](设计文档.md) | DS45-01..14、输入/执行/profile/结果合同 |
| 4 | [Alpha101覆盖清单](Alpha101覆盖清单.md) | 101个ID的静态数据和算子依赖；不是实现通过清单 |
| 5 | [Alpha101代表验收案例](Alpha101代表验收案例.md) | 20个独特配方、已知答案构造与错误区分 |
| 6 | [验收方案](验收方案.md) | 迭代45的30项AC、fixture、分仓与安装证据 |
| 7 | 本页第1节的四份计划 | 分轮任务、依赖与各自退出条件 |
| 历史 | [评审意见处理记录](评审意见处理记录.md) | 原六份评审意见的处置历史，不覆盖当前规范 |

六份原报告位于[已弃用目录](已弃用-外部评审报告-v0.2/README.md)，后续开发不再以其为依据。本轮保留原件和历史记录；发生当前文档冲突时应同步修订，不引用旧报告追加隐含要求。

## 4. 范围与分仓规则

20式固定为#1、2、3、4、7、9、13、29、48、56、58、62、63、67、81、84、92、96、100、101。45同时盘点全部101依赖并验收所需算子和PIT数据能力，但只实现20个诊断配方；46负责生产目录与完整101。公式内rank、行业去均值及formula_universe与fincore评价阶段的变换、共同池、horizon、组合权重分开，离线复评不改写历史公式值。

新增因子绩效、通用变换/合成/统计与报告归fincore；两个fincore叶子轮已有提交，精确提交与验收记录以对应仓库记录为准。Backtrader后续仍须接入并验收身份固定的已提交产物。原生采集/存储无需fincore。两仓均按“本轮实现→针对性验收→明确范围提交→下一轮”推进，不新建开发worktree；保留无关修改。数值能力、安装集成和真实市场绩效是不同证据，不互相替代。

025/026是拟交付的两个正式研究示例。当前027已改为真实FactorIndicator(panel_mode="next")的#3原生示例；旧的本地手动面板引擎及factor_strategy.py已删除，旧expression原型仅保留在Git历史。全资产研究需要声明对应字段、单位、时点和分类适用性；没有股票市值/行业字段的资产不能假造这些字段声称101式全部适用，也不承诺复现论文收益。

## 5. R0 原生示例与历史 expression 原型

[027示例](../../../../../examples/backtest/027_alpha003_panel_acceptance/README.md)当前展示真实FactorIndicator(panel_mode="next")的native算法。R0的范围、命令和证据见[开发与验收记录](开发与验收记录.md)；示例运行入口不自动运行测试。旧expression原型及其build(ctx)写法只存在于Git历史，历史边界见[原型验证记录](Alpha003原型验证记录.md)。

R0已将027改为真实初始化的FactorIndicator原生实现；旧本地手动factor_strategy.py已删除，expression原型源码仅可从Git历史追溯，历史类名为PanelFactorIndicator。R0提交7e3f517c4f43dbeb2e3d72b108f86f3d12b47740，39项独立原生用例通过，合并Indicator/SMA/ROC回归后为42 passed。证据级别为SOURCE_NATIVE_CEREBRO_R0_ONLY，不代表AC45-03/04/25/27或完整AC45通过。R3-S提交d9c6a631新增backtrader/research/alpha101_dependencies.json；Root执行3项测试通过，仅接受AC45-23静态登记部分，不是101个公式实现或完整AC45-23验收。20个native代表式仍为WIP；完整101个生产因子库为NOT_IMPLEMENTED。两个fincore叶子轮已有提交，具体身份由Root在开发记录中统筹；已安装产物与Backtrader集成仍须单独验收。47再提供正式build版本；历史expression原型不回写为native或build通过。

## 6. 当前开发与验收事实

| 范围 | 已发生事实 |
|---|---|
| R0 原生闭环 | Backtrader dev提交`7e3f517c4f43dbeb2e3d72b108f86f3d12b47740`；39项独立原生用例通过，与Indicator/SMA/ROC回归合并为42 passed；证据仅为`SOURCE_NATIVE_CEREBRO_R0_ONLY`。 |
| R3-S 静态登记 | Backtrader dev提交`d9c6a631`；登记文件`backtrader/research/alpha101_dependencies.json`；Root测试3 passed，仅接受AC45-23静态登记部分。 |
| 当前整体状态 | 正式AC45-01..30尚未整体最终验收；20个native代表式仍为WIP，完整101生产库仍为`NOT_IMPLEMENTED`。两个fincore叶子轮已有提交，精确记录由Root统筹。 |
| 本版范围 | 本次仅同步五份需求/设计/验收文档；不据组件结果推定AC PASS，不改历史原型记录。 |



R0与R3-S的完整实施/验收事实见[开发与验收记录](开发与验收记录.md)；本版正文、共同合同和四份计划继续作为后续实施入口。

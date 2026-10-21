# 迭代45–48因子研究文档入口

版本：**v1.1 状态同步稿**；更新：**2026-10-22**。R0 Alpha#3与R3-S证据的当前状态见[验收结果](验收结果.md)。R4的20个诊断配方源码矩阵38/38通过；R8使用已接受的Backtrader `8c02e07f` wheel与fincore `d7f65460` wheel完成20式installed聚合矩阵。严格复制验收7项也已通过。025/026最终wheel离线复评已在Backtrader `b2697f13`上完成：两个native复制运行和五个offline场景均PASS；same-config的evaluation ID及22张表一致，dataset未变，guard计数为0，period/weight变体均生成新ID。详见[最终离线复评归档](evidence/iteration45-offline-20261022/README.md)及[Root只读复核](evidence/iteration45-offline-20261022/output-review.md)。完整101个生产因子库仍为 **NOT_IMPLEMENTED**；本页只记录以上已验收范围，其他AC唯一状态见[验收结果](验收结果.md)。历史 expression 原型与当前 native 示例的边界见下文。

## 1. 四个迭代的顺序与出口

| 迭代 | 交付目标 | 独立验收 |
|---|---|---|
| [45：原生能力与研究闭环](迭代计划.md) | R4/R8的20个诊断配方矩阵、严格复制7项及025/026最终wheel离线复评已按各自范围通过；复评含2个native复制运行和5个offline场景 | AC45-01..30；其他AC唯一状态以[验收结果](验收结果.md)为准 |
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
- 已接受的R4源码矩阵为38/38，覆盖20个诊断配方的runonce/runnext、最终与中间节点、H边界及PIT/缺格区分。R8已接受矩阵绑定 Backtrader `8c02e07f`（wheel SHA-256 `217eebc31b2d488d254d88c0c927bcbe2bfb507586610b0e79b0045647ea0742`）和fincore `d7f65460`（wheel SHA-256 `fbd05395b193ee6510a97c54947c1c3d079f03ca3bd4d9677583519df783d607`）。另在最终`b2697f13` wheel上完成025/026离线复评：2个native复制运行和5个offline场景均PASS；same-config IDs及22张表哈希匹配、dataset字节不变，guard计数为0，参数变体ID不同。范围、路径和报告见[离线复评归档](evidence/iteration45-offline-20261022/README.md)。
- R8使用286-bar合成源网格中的136个研究格、6个资产，生成816条next-open标签；VWAP为独立合成序列（不是OHLC均值），美元成交额按声明的VWAP×share volume派生，字段带来源语义/单位/复权元数据；PIT分类、可用时间和显式公式池也保留来源边界。缺格不压缩，H预热与退化原因留在结果中。5440个唯一(time,signal,metric)键中3912条IC逐值通过、1528条退化状态和原因匹配；`PARTIAL`来自保留的预热/退化行，`max_loss=1.0`仅用于该诊断，不是收益或交易通过。数据是合成的，不表示真实市场绩效。

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

20式固定为#1、2、3、4、7、9、13、29、48、56、58、62、63、67、81、84、92、96、100、101。45同时盘点全部101依赖并验收所需算子和PIT数据能力，但只实现20个诊断配方；46负责生产目录与完整101。公式内rank、行业去均值及formula_universe与fincore评价阶段的变换、共同池、horizon、组合权重分开，离线复评不改写历史公式值。R4/R8的PASS限于这些诊断配方和安装统计矩阵，不要求每个因子有有效IC，也不要求IC为正或非零。

新增因子绩效、通用变换/合成/统计与报告归fincore；两个fincore叶子轮已有提交，精确提交与验收记录以对应仓库记录为准。Backtrader后续仍须接入并验收身份固定的已提交产物。原生采集/存储无需fincore。两仓均按“本轮实现→针对性验收→明确范围提交→下一轮”推进，不新建开发worktree；保留无关修改。数值能力、安装集成和真实市场绩效是不同证据，不互相替代。

025/026是拟交付的两个正式研究示例。当前027已改为真实FactorIndicator(panel_mode="next")的#3原生示例；旧的本地手动面板引擎及factor_strategy.py已删除，旧expression原型仅保留在Git历史。全资产研究需要声明对应字段、单位、时点和分类适用性；没有股票市值/行业字段的资产不能假造这些字段声称101式全部适用，也不承诺复现论文收益。

## 5. R0 原生示例与历史 expression 原型

[027示例](../../../../../examples/backtest/027_alpha003_panel_acceptance/README.md)当前展示真实FactorIndicator(panel_mode="next")的native算法。R0的范围、命令和证据见[开发与验收记录](开发与验收记录.md)；示例运行入口不自动运行测试。旧expression原型及其build(ctx)写法只存在于Git历史，历史边界见[原型验证记录](Alpha003原型验证记录.md)。

当前027是历史R0提交中的真实FactorIndicator原生示例；旧expression原型源码仅可从Git历史追溯。R0与R3-S记录及其他R轮/AC的唯一当前状态见[验收结果](验收结果.md)。R4的20个诊断配方source矩阵38/38通过；R8的installed矩阵绑定Backtrader `8c02e07f` 与fincore `d7f65460` 两个已接受wheel。严格复制验收7项通过，见[复制验收记录](evidence/iteration45-copy-20261022/README.md)。025/026最终wheel离线复评已通过，包含2个native复制运行和5个offline场景；same-config IDs与22张表哈希匹配、dataset字节不变、guard计数为0，period/weight变体ID不同，详见[复评归档](evidence/iteration45-offline-20261022/README.md)。完整101个生产因子库为NOT_IMPLEMENTED；迭代46–48尚未开发；历史expression原型不回写为native或build通过。

## 6. 当前开发与验收事实

| 范围 | 已发生事实 |
|---|---|
| R0 原生闭环 | Backtrader dev提交`7e3f517c4f43dbeb2e3d72b108f86f3d12b47740`；39项独立原生用例通过，与Indicator/SMA/ROC回归合并为42 passed；证据仅为`SOURCE_NATIVE_CEREBRO_R0_ONLY`。 |
| R3-S 静态登记 | Backtrader dev提交`d9c6a631`；登记文件`backtrader/research/alpha101_dependencies.json`；Root测试3 passed，仅接受AC45-23静态登记部分。 |
| R4 / AC45-28 | 20个代表诊断配方独立oracle源码矩阵38/38通过，双Cerebro模式、最终/中间节点、H和PIT/缺格边界；[开发记录](开发与验收记录.md)。 |
| R8 / AC45-29 | Backtrader `8c02e07f` + fincore `d7f65460` 已接受installed矩阵，1项聚合测试；816 labels、5440唯一IC键、3912有效IC、1528退化原因匹配；结果`PARTIAL`是保留预热/退化行。详见[安装验收证据](evidence/iteration45-twenty-installed-20261022/)。 |
| 严格复制 | 7项复制验收通过，具体范围见[复制验收记录](evidence/iteration45-copy-20261022/README.md)；最终wheel上的025/026离线复评另见[离线复评归档](evidence/iteration45-offline-20261022/README.md)。 |
| 当前状态索引 | 各R轮和AC的唯一当前状态见[验收结果](验收结果.md)。025/026最终wheel离线复评已通过；完整101生产库仍为`NOT_IMPLEMENTED`，迭代46–48尚未开发。 |
| 本版范围 | 本页同步R4/R8、严格复制和原型API边界；其余状态以验收结果页为准，不据组件结果推定完整AC45 PASS。 |



R0与R3-S的完整实施/验收事实见[开发与验收记录](开发与验收记录.md)；本版正文、共同合同和四份计划继续作为后续实施入口。

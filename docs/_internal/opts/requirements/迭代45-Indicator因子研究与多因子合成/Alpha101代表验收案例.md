# Alpha101 代表验收案例

版本：v0.8（验收配方附件；逐式执行状态均为 NOT_RUN）

本附件为迭代45的20个代表式诊断配方，供 AC45-28/R4 验证 Backtrader 原生公式能力、供 AC45-29/R8 验证20个 native 代表式及 fincore 的 Backtrader 与 fincore 已安装产物。45先有 R0 的 Alpha#3 最小原生闭环展示，随后 R1–R10 独立关闭当前 native 范围；R0本身不构成验收。迭代47/48的 build 实现、自动 H 和跨模式等价使用新增 build 专属 AC，不倒记为45通过。公式编号、完整表达式和原始常量以[论文Appendix A](https://arxiv.org/pdf/1601.00991)为准；下文的“结构草图”仅定位计算链，**不是完整公式，也不能替代原式**。实现验收前须对照原文冻结该编号的完整声明及所有常量；运行只读取本地冻结配方，不在运行时下载或解析PDF，不得为方便缩短窗口、改参数或删除节点。101式的数据和算子依赖见[Alpha101覆盖清单](Alpha101覆盖清单.md)，语义合同见[设计文档DS45-11至DS45-14](设计文档.md)，四迭代共用的网格/历史视图/缺格约定见[ALN-01..08](四迭代路线与对齐合同.md)。

本附件没有实现或登记生产因子类，也没有提供已通过的测试结果。本次先定稿文档，随后按用户授权实施45；截至本次规划定稿，功能 AC 均为 NOT_RUN。20个配方是45 native 范围的代表式诊断输入；完整101个native生产类由迭代46实现，build实现由迭代48完成。尚未选入的81式仍须在迭代45按覆盖清单完成字段、算子层独立golden、原始窗口需求及lookback传播能力的语义覆盖（不要求这81式的精确H），不能据此豁免算子层验收。45对20式的 H 由人工根据明确窗口依赖核算；不编译 DAG、不自动推导 H。build 自动 H 属迭代47新增能力。现有 027 expression 原型源码保留历史类名 `PanelFactorIndicator`，本轮不改该原型代码；它不构成本轮 `FactorIndicator` native 通过，也不等同于迭代47的 build 前端。

## 配方共同合同

- 每个例子使用非生产合成数据，至少固定完整UTC grid、资产键、字段绑定、formula_universe、版本化行业分类、available_at、信号时点和源数据快照。市场行可包含OHLCV、由声明口径生成的VWAP、美元成交额及ADV；cap和sector/industry/subindustry均使用point-in-time版本。禁止从未来数据、晚发布值或未来成员状态回填过去。
- 每个案例定义文件必须保留Alpha ID、论文出处、完整原式、原始窗口常量、operator_profile=alpha101-v1、字段/分类绑定和确定性输入生成器版本。定义源建议放在拟新增的独立配方文件中；不得把简写草图当成运行定义。
- 独立expected由拟新增的参考实现和独立fixture生成。参考实现逐资产、逐grid标量计算，允许直接读固定输入，但不得调用候选生产公式、生产 Indicator/面板执行实现或生产 build 编译器，也不得从生产运行结果反向制作expected。先固定expected和关键中间节点，再运行候选公式。逐节点记录有限值/缺失、原因、时间戳和适用资产池。
- alpha101-v1中rank是**当前时点横截面公式池**上的平均秩/n；Ts_Rank/ts_rank是**同一资产完整时间窗**的平均秩/d。不得交换轴或互相代用。rank只对当前有效公式成员计算，并列取平均秩。scale按当前截面 a*x/sum(abs(x))；IndNeutralize按当前PIT分组做组内等权去均值，单成员输出0。
- 所有窗口在载入原式后才向下取整；小数原参数仍保存在manifest中。delay/delta按完整grid位移，滚动窗要求完整grid，不得删除、压缩、前填或缩短缺口。以下给出的 H/最低 grid 是45 native 配方的人工依赖核算，须由独立参考复算；所有涉及ADV的这些H均按美元成交额派生ADV的路径计算，不按预计算ADV字段叶子计算。47 build 前端再单独验收自动 H。
- comparison/where使用三值逻辑。比较结果进入任意数值算子（包括算术、rank、decay及最终输出）时，true=1、false=0、unknown保持缺失；不得使用Python bool(NaN)。where只按被选分支决定有效性，unknown条件无效；未选分支的已知域无效不污染结果，意外异常仍失败。
- 每个案例拆分“至少一条有限输出的正例”和可区分的结构/边界例。无效数据应形成既定缺失状态，不能把整式全NaN或skip算作通过。常规共性还要做资产列重排不变、未来扰动不改变过去输出、晚发布数据不可提前可用、成员池按当日PIT生效、时序缺bar不压缩历史。45 native 用真实 FactorIndicator 执行；47新增 build AC 在同一确定性输入上验证 build/native 等价及混合装配，并单独验收 build 自动 H；45不报告 build/跨模式功能通过。45 R8/AC45-29在已安装的Backtrader/fincore上验证20个native代表入口、有效前向标签、公开绩效API及二值/常数退化reason；R10关闭AC45-20/30的组合能力与四迭代交接。不要把47/48的build集成证据倒写为R4公式实现结果。

建议把冻结定义存为拟新增的Alpha101案例manifest，把独立参考代码存为拟新增的reference测试资源，并将每例的输入与expected节点表以内容哈希绑定。下列“独立expected”均指这类无生产节点依赖的参考来源；相关产物尚未创建，当前状态仍为NOT_RUN。

## 手算定序案例

### AF45-003 — Alpha#3：截面rank后做时序相关

状态：NOT_RUN。论文定位：Appendix A，Alpha#3；[官方原文](https://arxiv.org/pdf/1601.00991)。

结构草图：先逐日计算rank(open)和rank(volume)，再对每资产的两条rank序列计算10日相关，最后取负。运行时必须使用论文完整Alpha#3原式。

输入为A、B、C三资产×连续10日。表中为未归一化的整数秩，每行都是1、2、3的有效排列；实际公式rank为表值/3。raw open=10+表中open整数，raw volume=100×表中volume整数；所有行固定low=0.5、high=20、close=10，保证OHLC有效。volume整数前九日取4减open整数，末日与open整数相同。H=9，至少10个grid。

| 日期 | open rank (A,B,C) | volume rank (A,B,C) |
|---|---|---|
| d1 | (1,2,3) | (3,2,1) |
| d2 | (2,3,1) | (2,1,3) |
| d3 | (3,1,2) | (1,3,2) |
| d4 | (1,2,3) | (3,2,1) |
| d5 | (2,3,1) | (2,1,3) |
| d6 | (3,1,2) | (1,3,2) |
| d7 | (1,2,3) | (3,2,1) |
| d8 | (2,3,1) | (2,1,3) |
| d9 | (3,1,2) | (1,3,2) |
| d10 | (1,2,3) | (1,2,3) |

rank实现值可记为rank/3，相关系数对同一正比例缩放不变。独立手算expected：d10 A、B、C的Alpha#3分别为17/23、1、17/23；这一输出不是常数。参考程序须另外记录各资产10点输入序列、均值、Pearson分子/分母、相关系数和取负后的最终值。

区分错误实现：把顺序改成先算每资产10日raw correlation，再横截面rank并取负，精确算术参考下得到(-5/6,-1/3,-5/6)，与正确输出明显不同；浮点相关的舍入可能打破两个数学并列值，但错误顺序输出仍全部为负，不能据其浮点ties强制相同次序。另做一次只把B在d10的open从12改为9.5，使d10次序从A<B<C变为B<A<C，并保持其他价格、volume和历史行不变；A的当前open rank由1变2，其正确输出从17/23变为sqrt(20/23)。这验证另一个资产通过当期截面rank影响目标资产。缺少任一日期时10日窗无输出且不压缩；资产顺序重排后按键对齐结果完全相同。

AF45-003在迭代45只验收统一 `FactorIndicator(panel_mode="next")` 的原生实现：使用真实初始化的 FactorIndicator、params、self.datas、Lines、owner/clock/minperiod 与 `once_via_next`（next-only 基线），手写平均秩、固定 grid 历史及 Pearson，并将每资产结果写入真实 scalar line；独立对照上面的 Fraction/手算 oracle，不以另一候选实现作唯一预期。按显式 grid 预先对齐全部研究资产，缺格为 NaN、不沿用旧值，Strategy.next 只采集。覆盖两种 Cerebro 模式、资产重排、未来扰动、单资产/全池/尾部缺格、并列与零方差，比较输出、有效性原因和时间对齐；若提供原生 `once` 优化，必须逐 grid 索引证明与 `next` oracle 的输出及有效性等价；FactorIndicator 内的原生 SMA/ROC 子 Indicator 依真实 BT tree 调度，多个研究因子并行时结果不变，next 每 grid 只调用一次且状态不串用。另以真实 SMA/ROC 子指标验证原生生命周期兼容；#3本身的手写窗口历史不能替代这个检查。R0用#3先展示最小闭环，R4再完成本代表配方；两者当前均为NOT_RUN。迭代47由新增 build AC 实现 build 版本并与同一独立 oracle 和 native 结果等价。现有027 expression原型源码保留历史类名 `PanelFactorIndicator`，本轮不改该原型代码；它不构成本轮 `FactorIndicator` native通过，也不等同于迭代47的build前端。

### AF45-004 — Alpha#4：截面rank进入Ts_Rank

状态：NOT_RUN。论文定位：Appendix A，Alpha#4；[官方原文](https://arxiv.org/pdf/1601.00991)。

结构草图：每个日期先对low做横截面rank，再按资产取9个grid的Ts_Rank并取负。实际定义必须使用原式及窗口9。

用A、B、C三资产和9日序列构造raw low为下表整数；open=10、close=11、high=12、volume=100。表中也是未归一化的每日整数秩，实际截面rank为表值/3。H=8，至少9个grid：

| 日期 | A | B | C |
|---|---:|---:|---:|
| d1 | 1 | 2 | 3 |
| d2 | 2 | 1 | 3 |
| d3 | 3 | 1 | 2 |
| d4 | 1 | 3 | 2 |
| d5 | 2 | 1 | 3 |
| d6 | 3 | 1 | 2 |
| d7 | 1 | 2 | 3 |
| d8 | 2 | 1 | 3 |
| d9 | 3 | 1 | 2 |

每行均为有效排列。独立expected：A的当前rank=3在其9个rank值中出现三次，占排序位置7、8、9，平均秩8，故正确Alpha#4为-8/9。按错误顺序先做各资产raw low的9日Ts_Rank，再对这三个结果做截面rank并取负，结果为A=-1、B=-2/3、C=-1/3。参考记录每个资产完整窗口的值频数、当前值average-rank、除以9的结果及最终负号。窗口缺一天时不得得到9点输出；缺口恢复后按grid形成完整窗。

## 其余18个配方

每个配方都必须从论文对应ID读取完整原式，保留所有嵌套运算、分数参数和符号。结构草图只作为中间节点断言，不代表可直接运行的简式。

### AF45-001 — Alpha#1

状态：NOT_RUN。来源：论文Appendix A Alpha#1。结构草图：returns负值条件选择stddev(returns,20)或close，SignedPower指数2，再取5窗Ts_ArgMax并横截面rank，最后减0.5。合成至少4资产×25 grid，设计有返回正负与相同极值位置；严格保留20、2.、5。预期来源为独立滚动方差、分支选择、最老并列argmax、最终rank参考；核对stddev ddof=0、5窗最老位置编号和排序并列。H应为24、至少25行。错误区分：用最近一次并列极值、把Ts_ArgMax改成rank位置、或省略最终0.5偏移。边界：returns比较unknown不得当false，不能回退选close。

### AF45-002 — Alpha#2

状态：NOT_RUN。来源：Alpha#2。结构草图：rank(delta(log(volume),2))与rank((close-open)/open)的6窗相关后取负。用4资产×8个连续grid，open和volume全正；设计非恒定rank与相关输入，防止常数窗。独立expected输出所有资产的两条rank输入、6对样本Pearson值和负号；保留原始窗口2与6。H=7、至少8行。错误区分：将log放到delta外或内错误、用close-to-open价差代替比值、把横截面rank变成Ts_Rank。边界：零/负volume或零open对应的数学域invalid明确传播，不由参考代码静默修复。

### AF45-007 — Alpha#7

状态：NOT_RUN。来源：Alpha#7。结构草图：比较adv20与volume；true分支为Ts_Rank(abs(delta(close,7)),60)乘sign(delta(close,7))再取负，false分支为-1。输入覆盖adv20<volume与不满足两分支，另有等值时的false结果；精确使用7和60。独立expected记录美元ADV、shares volume、条件三值、delta、abs、60窗rank和逐支where结果。H=66，至少67行才能验证完整true分支。错误区分：把adv20与volume关系方向反转、把美元成交额的20日均值替换为股数volume的20日均值、将unknown视作false，或在where前求无效未选分支并污染结果。边界包括未满60的true分支、volume缺失和条件unknown。原式直接比较美元ADV与股数volume；本profile保留这一跨单位表达式，不作隐式单位换算，不将该比较解释为同量纲物理量。合成true分支可用低美元价格和充分变化的成交量构造，不能通过把ADV改成平均股数达成。

### AF45-009 — Alpha#9

状态：NOT_RUN。来源：Alpha#9。结构草图：根据delta(close,1)的5窗ts_min和ts_max选择当前delta或其相反数。单资产close序列取100、101、102、101、100、102，最近5个delta为1、1、-1、-1、2；d6输出手算为-2。独立expected逐项核对delta序列、min=-1、max=2和分支。原式窗口1和5不得变更。H=5、6行。错误区分：窗口含当前/不含当前、把min/max互换或把条件“并非全正或全负”错作仅看当前符号。边界：中间缺bar时窗口不压缩，窗不完整时结果为缺失。

### AF45-013 — Alpha#13

状态：NOT_RUN。来源：Alpha#13。结构草图：rank(close)、rank(volume)，5窗协方差，横截面rank后取负。输入为A/B/C/D×5日，close和volume的每日整数秩表相同：d1=(1,2,3,4)、d2=(1,2,3,4)、d3=(1,2,4,3)、d4=(3,1,4,2)、d5=(4,3,1,2)。raw close=10+该整数、raw volume=100×该整数；open=10、low=9、high=15。各日是有效排列，实际公式rank为整数/4；列和为10/10/15/15，均值为二进制可精确表示的1/2、1/2、3/4、3/4，避免以浮点近似并列作为验收前提。

独立手算expected：ddof=0的covariance依A/B/C/D为1/10、1/40、3/40、1/20，均不相同；最终Alpha#13为(-1,-1/4,-3/4,-1/2)。参考逐节点核对均值、中心化乘积、协方差和末端rank。H=4、至少5日。错误区分：把covariance替成correlation会使本例四项相关均为1，最终全为-5/8；只做时间rank、不做末端rank或改变负号也必须被识别。ddof=1通过中间covariance节点识别：统一乘正常数不改变末端rank，不能只靠最终值检验ddof。并列平均rank另由AC45-26的精确重复输入fixture验收；本式少于5个完整样本不输出。

### AF45-029 — Alpha#29

状态：NOT_RUN。来源：Alpha#29。结构草图：close减常数1后delta(5)，多层rank和scale，log/sum/ts_min嵌套，product后由数值RHS的min窗口再与delay(-returns,6)→Ts_Rank(5)分支相加。此草图不替代完整原式；必须按论文保留delta的5、ts_min的2、sum的1、product的1、min的5，以及delay的6、Ts_Rank的5，并保存原括号和rank层数。使用至少12日、4资产以上；close保持>1，输入按生成器挑选使sum/log/product定义域有效且各中间序列不全相同。独立expected按完整标量树计算并逐项存储delta、ts_min、sum、log、scale、所有rank、product、min和第二分支，不从生产图取得节点。结构区分：把min(expr,5)误解为两表达式逐点min，或把rank/scale互换；边界检查log正域、缺bar完整窗与精确原常量。预热以独立人工依赖计算核对；alpha101-v1结构推导预期H=11，最少12 grid。

### AF45-048 — Alpha#48

状态：NOT_RUN。来源：Alpha#48。结构草图：250窗相关(delta(close,1), delta(delay(close,1),1))，与delta(close,1)相乘并除close，按subindustry去均值，再除250窗的简单收益平方和。至少4资产×252日，设置多个subindustry和可手算的非恒定收益；close全正。独立expected逐点核对两条相关输入、250窗Pearson、分子、subindustry均值、平方收益和、最终比值。精确保留窗口250和指数2。相关分支最大历史H=251，至少252 grid；不得退化成更短窗。错误区分：把第二相关输入简化为delta(close,1)、把indneutralize移到除法之后、忽略分母或采用样本方差式分母。边界：缺一日的窗口invalid；单成员subindustry去均值为0，随后依分母规则判断。

### AF45-056 — Alpha#56

状态：NOT_RUN。来源：Alpha#56。结构草图：两个rank相乘后取负：一支是sum(returns,10)除以sum(sum(returns,2),3)，另一支是returns×PIT cap。4资产×11日以上；cap采用至少两个可见版本并在生效grid才切换。独立expected记录close-to-close returns、两层sum、cap时间版本、两支横截面rank、乘积及外层负号。窗口10、2、3和cap不得替换成close市值或用未来版本。H=10、至少11行。错误区分：将cap错当ADV/成交额、使用未来cap版本或把嵌套sum窗口相加成错误定义。边界：首个无可用前收的return缺失，截面rank仅对当前公式池有限值计算。

### AF45-058 — Alpha#58

状态：NOT_RUN。来源：Alpha#58。结构草图：VWAP按sector去均值，和volume做correlation(3.92795)，线性衰减(7.89291)，再Ts_Rank(5.50322)并取负。4资产×13日以上，sector至少两个且组成在PIT时点确定。独立expected核对组均值、corr的floor(3)=3、decay floor(7)=7各权重1…7、Ts_Rank floor(5)=5。历史H=12，最低13行。错误区分：用industry或subindustry替换sector、忽略fractional windows原值、把Ts_Rank理解成跨资产rank，或对缺项重归一decay权重。边界：sector晚发布变更不能回写过去；窗缺一个grid整窗invalid。

### AF45-062 — Alpha#62

状态：NOT_RUN。来源：Alpha#62。结构草图：一支是rank(correlation(vwap,sum(adv20,22.4101),9.91009))；另一支是含rank(open)重复项及high/low组合比较的嵌套布尔，再rank；比较两rank并以-1缩放。至少4资产×49日，adv20由日美元成交额计算。独立expected保存floor后22与9的窗口、各rank、相关、内层比较三态、外层比较和数值输出。H=48，至少49行；每分数常量原样入manifest。区分错误实现：去掉重复rank(open)、把22.4101或9.91009直接四舍五入、把unknown比较当false，或没有实现比较布尔进入rank/算术时true=1、false=0、unknown缺失。至少构造true、false和unknown三个路径。边界：缺adv历史不能填0。

### AF45-063 — Alpha#63

状态：NOT_RUN。来源：Alpha#63。结构草图：第一支industry去均值close→delta(2.25164)→decay(8.22237)→rank；第二支按0.318108混合VWAP/open，和sum(adv180,37.2467)做corr(13.557)→decay(12.2883)→rank；两rank相减后取负。4资产×239日以上，构造时变PIT industry并确保两个分支都有限、输出非恒定。独立expected列出组均值、delta floor2、decay floor8、ADV180、sum floor37、corr floor13、decay floor12及最终差。分数常量完整保存，H=238、最低239 grid。错误区分：ADV期限错为20/120、sector替代industry、输入混权系数被缩短或去掉其中一支。边界：成员重分类只从生效时点改变组；分类unknown不归入默认组。

### AF45-067 — Alpha#67

状态：NOT_RUN。来源：Alpha#67。结构草图：rank(high-ts_min(high,2.14593))作为普通实数幂底数；幂指数是rank(correlation(sector-neutralized VWAP, subindustry-neutralized ADV20,6.02936))，最后取负。至少6资产×25日，布置不同sector/industry/subindustry且各组有多个资产。独立expected记录两个分组均值、adv20、corr floor6、两项rank、底数/指数及逐资产ordinary power。H=24、至少25 grid。两种分组层级映射必须不同；测试错误地把两者统一到sector或subindustry时expected可分辨。错误实现：把^解析为XOR、颠倒底数与指数或用错误行业轴。有效rank底数必为正，普通幂与SignedPower在此相同，不能声称本式数值能区分两者。负底数/非整数指数的普通幂域边界单列AC45-26算子测试，不注入不可能的rank值冒充本式边界。

### AF45-081 — Alpha#81

状态：NOT_RUN。来源：Alpha#81。结构草图：rank(correlation(vwap,sum(adv10,49.6054),8.47743))的4次幂，经rank后做product(14.9655)，log和rank；与rank(correlation(rank(vwap),rank(volume),5.07914))比较并取负。至少4资产×78 grid，vwap、volume和美元ADV10有效；独立expected逐点留存sum、corr、rank、普通幂、product、log、最终rank和比较。完整保留49.6054、8.47743、指数4、14.9655、5.07914。H=77、最低78行。结构区分：将product替为sum、把log(product(x))错写为product(log(x))、漏掉任一rank层或把最终布尔留作Python bool。边界：正例确保product>0且log有限；log算子的非正输入在AC45-26单独测试并返回DOMAIN_ERROR，不能把有效正rank的乘积强行替换成负数冒充本式路径。

### AF45-084 — Alpha#84

状态：NOT_RUN。来源：Alpha#84。结构草图：Ts_Rank(vwap-ts_max(vwap,15.3217),20.7127)作为SignedPower底数；delta(close,4.96796)是逐时点指数。至少4资产×34日，生成令TS_rank底数为正且指数包含正、负、0的窗口。独立expected记录floor(15)=15的ts_max、floor(20)=20的ts_rank、floor(4)=4的delta和SignedPower逐点结果。H=33、最低34 grid。错误区分：把指数当固定常量或把时序rank做成截面rank。有效Ts_Rank底数在(0,1]，所以普通幂与SignedPower在本式有效路径相同，底数0或负数也不可达；这些差异留给AC45-26独立算子测试。此式验证动态正/负/零指数及缺窗传播，不注入非法rank值。

### AF45-092 — Alpha#92

状态：NOT_RUN。来源：Alpha#92。结构草图：两个分支做pointwise min：布尔比较(midpoint+close < low+open)进入decay(14.7221)→Ts_Rank(18.8683)；另一支是correlation(rank(low),rank(adv30),7.58555)→decay(6.94024)→Ts_Rank(6.80584)。4资产×46日以上，设置布尔true、false、unknown和正ADV30。独立expected分别核对floor后的(14,18)和(7,6,6)窗口、布尔数值转换、decay权重、Ts_Rank与逐资产min。第二支最大H=45，至少46 grid。错误区分：把两个表达式min错编成单参数滚动min，或将unknown比较当False/0；任何比较进入数值算子时true=1、false=0、unknown缺失。边界：缺一格保持全窗invalid。

### AF45-096 — Alpha#96

状态：NOT_RUN。来源：Alpha#96。结构草图：pointwise max连接两条不同历史支路。第一支correlation(rank(vwap),rank(volume),3.83878)→decay(4.16783)→Ts_Rank(8.38151)；第二支Ts_Rank(close,7.45404)与Ts_Rank(adv60,4.13242)做corr(3.65459)，再Ts_ArgMax(12.6556)→decay(14.0365)→Ts_Rank(13.4143)。至少4资产×101 grid；设计两分支值有交叉，确保max选择会切换。独立expected保存分支节点、adv60、各floor窗口、argmax完整窗口位置和最后的负号。第二支H=100，最低101 grid。错误区分：把max(表达式,表达式)误做滚动窗口max，漏掉argmax、把argmax最老/最新编号颠倒，或把fractional窗口改成短参数。边界：参数profile规定并列argmax取最早位置；不同资产缺历史时只使该资产相应窗口无效。

### AF45-100 — Alpha#100

状态：NOT_RUN。来源：Alpha#100。结构草图含三次IndNeutralize调用：第一支rank的价格位置×volume结果连续两次按subindustry去均值，再scale，最后乘1.5（1.5在scale外）；第二支corr(close,rank(adv20),5)减rank(ts_argmin(close,30))，再按subindustry去均值和scale；两支相减后乘volume/adv20并取负。至少6资产×30日，构造非恒定量和至少两个sector/industry/subindustry层次，且层级成员划分不同。独立expected逐节点记录三次调用的输入、group key、组均值、输出与逐节点参考计算trace；需要核对节点数、顺序、层级和复用边。相同固定分组的重复去均值可能幂等，**不得声称同组第二次去均值必定造成数值变化**；应由图结构/执行追踪验证两次调用仍保留，并用将某调用错误映射到sector/industry的变体区分。另用非零向量核对1.5×scale(x)与错误的scale(1.5×x)：后者会抵消正系数1.5，必须由中间及最终数值识别。主历史H=29，至少30 grid；精确保留1.5、scale默认a=1及power/profile语义。边界：组变更只从PIT生效时间更新，未知分类显式invalid；scale分母为0时按profile返回缺失并显式记录原因。

### AF45-101 — Alpha#101

状态：NOT_RUN。来源：Alpha#101。结构草图是当期(close-open)除以(high-low+0.001)。单行正例open=10、high=16、low=8、close=14，expected=4/8.001。独立expected以Decimal或高精度标量先算，再按float64合同比较；H=0，精确保留0.001。错误区分：漏掉常数、把分母改为high-low、或错误缩放为百分比。边界：high=low且close=open时分子0，分母仍为0.001，输出有限0；若OHLC不满足输入一致性，由字段验证按合同处理，不允许参考实现静默修正。

## 执行记录与交接

20个固定案例ID为AF45-001、AF45-002、AF45-003、AF45-004、AF45-007、AF45-009、AF45-013、AF45-029、AF45-048、AF45-056、AF45-058、AF45-062、AF45-063、AF45-067、AF45-081、AF45-084、AF45-092、AF45-096、AF45-100、AF45-101；状态全为NOT_RUN。AC45-28/R4需逐式记录独立known-answer、有限输出正例、边界例、完整原式/参数身份、人工H和独立参考隔离证据。AC45-29/R8还需记录两个仓的安装版本、dev提交、wheel哈希与实际import路径，并将配方/输入复制到外部运行目录运行；源码checkout或editable导入不满足该项。二值式或常数式的fincore退化必须按原因报告，不能为了五分位而改造公式输出。迭代47/48 build安装和自动H由新增build专属AC覆盖，当前不构成45通过。

迭代46 native、迭代47 build 20式、迭代48全101 build的库交接按Alpha101覆盖清单逐项生成生产声明及身份/来源/profile/字段/行业层级/H/参数/摘要/timing/适用资产语义；47 build 前端另提供表达式来源和编译依赖记录。全量交接要求全算子支持，不允许用这20个配方替代剩余81条公式的实现。不得将本附件的NOT_RUN写成PASS，也不得据此宣称复现了论文真实市场收益、原作者实现或账户交易结果。

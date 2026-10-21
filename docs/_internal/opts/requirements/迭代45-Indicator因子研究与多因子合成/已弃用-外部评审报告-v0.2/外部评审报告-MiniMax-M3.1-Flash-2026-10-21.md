# 迭代 45《Indicator 因子研究与多因子合成》独立外部评审报告

- **审阅模型**：MiniMax-M3.1-Flash
- **审阅方**：Qoder Agent（桌面版编码智能体）
- **审阅日期**：2026-10-21
- **审阅对象**：`dev` 分支 commit `8457e8a53cec879a48de079b3da9c7f56ccece41`（父提交 `57b572ed8`）下的迭代 45 方案包五份文档
- **方案包**：[README.md](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/README.md) · [需求文档.md](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/需求文档.md) · [设计文档.md](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md) · [验收方案.md](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md) · [迭代计划.md](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/迭代计划.md)
- **只读参考**：`fincore` 仓库 `dev@2354bb560788f372502151a8b1b53accf536a6c0`（`0.5.1.dev0`），只读取源码，未做任何改动
- **记录格式**：按本包 README §4 建议字段，问题编号自 REVIEW45-001 起顺序编号
- **审阅方式与边界**：纯静态审阅 + fincore 源码逐条比对 + 全部验收 fixture 的手算复算。**未执行任何 AC**（22 条 AC 全部仍为 `NOT_RUN`），未运行任何测试，未修改、未提交仓库任何文件。方案包中的每一处数值断言都做了本地手算复核，全部吻合；下文只列**未被复算推翻、且经源码验证确实成立**的问题。

---

## 关于本目录内既有两份评审报告的关系

本目录已有 `外审报告-Qoder-2026-10-21.md` 与 `迭代计划独立审阅报告-2026-10-21.md`。二者均针对 **`57b572ed8` 及其之前的文档内容**编写；当前 HEAD `8457e8a53` 已重整了需求/设计/验收的章节结构，二者中关于"结果状态枚举矛盾""交叉引用大面积失效"等条目在当前版本已不成立（验收方案 §8.3 现为 `OK/PARTIAL/UNEVALUABLE`，与设计文档一致），故本报告不复述、不重新提出这些已修项。

三份报告的 `REVIEW45-001…` 编号各自独立、互不对应。收口时**建议以本报告的编号为唯一引用基准**（本报告面向当前 HEAD），或由 README §5 的收口流程统一重编。

---

## 一、总体结论

**结论：方案整体技术判断可靠，不建议推翻重来；但基线确认前需要先关闭 5 个"阻止基线确认"项。**

方案的优点是真实的、且不是客套话：分位归属先于标签掩码计算（DS45-06:189）、`dataset_id`/`evaluation_id` 双身份拆分（DS45-09:257）、common 池重新变换（DS45-06:177）、显式声明 IID/不宣称 HAC（DS45-07:206）、结果状态（OK/PARTIAL/UNEVALUABLE）与退出码分离（DS45-08:251）、fincore 先提交再由 Backtrader 接入的两仓顺序（DS45-01:26）、用 Broker submit/cancel 计数器作为"无下单"证据（AC45-01），这些都是同类研究框架里很少有人写清楚的部分。

但方案存在一个反复出现的模式：**语义合同写在了设计文档里，却与两处现实不闭合**——一是与 fincore 现有实现不闭合（DS45-07 的差异表漏掉了最关键的两条），二是与"损失/覆盖率"这套统计口径自身不闭合。前者会导致 R2/R4 直接返工，后者会让示例在验收阶段产出与预期不符的数字。

按严重程度分：**5 项阻止基线确认、7 项实施前需澄清、5 项可选建议**。

---

## 二、阻止基线确认

### REVIEW45-001 · `max_loss` 把标签结构性尾部当作数据质量缺陷

- **定位**：[设计文档.md:238](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L238)（DS45-08）、[设计文档.md:147](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L147)（DS45-05 标签表）、[设计文档.md:282](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L282)（DS45-10）；[验收方案.md:62](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L62)、[验收方案.md:186](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L186)
- **严重程度**：阻止基线确认
- **问题与影响**：`max_loss=0.35` 定义为 `(候选数 − 有限信号与该 h 标签配对数)/候选数`，分母是"研究区间内该 group 已知 universe=true 的候选行数"。而默认标签 `next_open_to_open = open[t+1+h]/open[t+1] − 1` 天然需要 h+1 个未来 bar（DS45-05:147 自己写了"必须多备 h+1 个后续 bar"）。于是**研究区间的最后 21 个 bar（h=20）必然没有标签配对**，而它们是有有限因子值的合法候选行，必然计入损失分子：

  | 场景 | 分母 | 结构性尾部损失 | 占比 |
  |---|---|---|---|
  | 完整研究期 260 bar | 260 | 21 | 8.08% |
  | development 段 160 bar | 160 | 21 | 13.13% |
  | validation 段 100 bar | 100 | 21 | 21.00% |
  | 研究区间 60 bar | 60 | 21 | **35.00%（恰等于上限）** |
  | 研究区间 59 bar | 59 | 21 | **35.59%（超限）** |

  后果是：任何短于 60 个研究 bar 的窗口（一次快速研究、一个更短的示例、或用户自定义研究区间）在默认 `periods=(1,5,20)` 下必然抛 `DataQualityError(code=LOSS_LIMIT_EXCEEDED)`，而不是返回带诊断的 `PARTIAL`。这把"标签数学上需要未来 bar"这一**结构性事实**与"数据质量有缺陷"混为一谈，且失败形态是硬拒绝而非可读诊断。设计文档:282 只说"较短段应明确检查其边界损失是否超过 max_loss"，没有给出可判定的阈值或规则，实施时无从下手。
- **建议**：在 DS45-08 明确二选一（并同时补一条可断言的公式）：
  1. **把结构性尾部排除出 max_loss 分母**，另设独立诊断项 `label_tail_unavailable`（分母 = 研究区间内"标签可得窗口"的候选行数）；或
  2. **保留现定义并写死可行域**：`有效研究长度 N 须满足 (h+1)/N ≤ max_loss`，即 h=20、max_loss=0.35 时 N ≥ 60（60 恰在上限，59 即超限），并在示例验收中把该不等式写成显式断言。

  两者可同时做：分母排除结构性尾部 + 另报尾部占比诊断 + 给出可行域公式。无论选哪个，DS45-10:282 的"检查其边界损失是否超过 max_loss"必须替换成可判定的数值规则。
- **处置**：待处理。**必须修改**。这是实施前必须先定的语义，且会改变 R2 的 fincore 增量范围（需在 fincore 侧新增对应入口/参数），属于范围变更，须同步更新需求文档与对应 AC。

### REVIEW45-002 · `max_loss` 口径与 fincore 现有 `prepare_factor_data_by_horizon` 不兼容，DS45-07 差异表漏列

- **定位**：[设计文档.md:238](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L238) vs [设计文档.md:215](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L215)（DS45-07 差异表）、[设计文档.md:104](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L104)（"可复用现有 `prepare_factor_data_by_horizon`"）；fincore [data.py:321-335](file:///D:/source_code/fincore/fincore/factor_analysis/data.py#L321)、[data.py:379](file:///D:/source_code/fincore/fincore/factor_analysis/data.py#L379)、[data.py:530-535](file:///D:/source_code/fincore/fincore/factor_analysis/data.py#L530)
- **严重程度**：阻止基线确认
- **问题与影响**：DS45-08 明确"分位损失另以有限配对数为分母报告，**不重复计入该上限**"，验收方案:186 复述同一口径。但 fincore 现状是：

  ```python
  # data.py:321-335
  binning_loss = (forward_count - binning_count) / input_count
  total_loss = factor_loss + forward_loss + binning_loss
  ```

  即**分位损失被算进 `total_loss`**，而 `total_loss > max_loss` 时直接 `raise FactorLossExceededError`。后果有三：
  1. 直接复用该入口得到的 `max_loss` 语义与 DS45-08 不同：分位退化会推高 total_loss 并触发 `LOSS_LIMIT_EXCEEDED`；
  2. 这与 DS45-06:191"分位失败不删除本来可计算的 IC"、DS45-06:189"记录 `QUANTILE_DEGENERATE`"直接冲突——一旦分位损失把上限顶破，整个 slice 抛异常，IC 一个都拿不到；
  3. `quantize_factor(..., no_raise=float(max_loss) != 0)`（data.py:379/504）意味着 max_loss≠0 时走 raise 分支，**根本无法实现"记录 QUANTILE_DEGENERATE 并保留 IC"**。

  DS45-07 差异表只写了"补齐通用预计算/next-open 标签路径"和"不能直接套旧路径丢短周期样本"，没有记录"旧路径的 loss 口径含分位损失"与"`no_raise` 绑定 max_loss"这两条。R2 一旦照差异表实现，验收方案:192 断言的"分位退化只使该截面的分层指标不可用、不抹除样本合法的 IC"必然失败。
- **建议**：在 DS45-07 差异表新增一行，把 `prepare_factor_data_by_horizon` 的复用范围明确降级为"仅可复用其 binning 前置于标签掩码之后的顺序约束"，并在 fincore 侧新增符合 DS45-08 口径的公开编排入口（把 factor/label/quantile 三项损失拆成独立分项，`no_raise` 与 `max_loss` 解耦）。这会新增一项 fincore 增量，须按 DS45-01:26 的顺序先在 fincore 提交。
- **处置**：待处理。**必须修改**（设计文档差异表 + 验收方案对应 AC 增补断言）。

### REVIEW45-003 · 标签构造的"完整 grid"契约与 fincore 现有实现相反

- **定位**：[设计文档.md:152](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L152)（"在完整 grid 上 shift，不在各资产删去缺失的价格序列上 shift"）、[设计文档.md:116](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L116)（prices"行按完整 grid；缺行重建为 NaN，不删除网格行"）；fincore [data.py:177](file:///D:/source_code/fincore/fincore/factor_analysis/data.py#L177)、[data.py:192](file:///D:/source_code/fincore/fincore/factor_analysis/data.py#L192)
- **严重程度**：阻止基线确认
- **问题与影响**：现有 fincore 标签构造是：

  ```python
  # data.py:177
  shared_dates = pd.DatetimeIndex(factor_dates.intersection(prices_index).sort_values())
  # data.py:192
  base_returns = selected_prices.pct_change(raw_period if cumulative_returns else 1, fill_method=None)
  ```

  两个问题：
  1. `intersection` 把"价格矩阵缺行"从"重建为 NaN"变成了**删除 grid 行**。DS45-03:116 承诺的"不删除网格行或填价格"在复用路径上不成立；更严重的是，被静默裁掉的日期不进任何分母，直接压低 loss 分母（DS45-08:236 要求分母在剔除前确定）——这正是"不能通过先缩池隐藏它"要防的情形。
  2. `pct_change` 只有 close-to-close，**没有 open 序列入口**，而默认标签是 `next_open_to_open`。

  DS45-07:215 承认 next-open 路径要补齐，但没提 intersection 这条与 DS45-03/DS45-05 同时冲突的行为。若不显式写入约束，R2 极可能"顺手复用"而把 grid 裁掉。
- **建议**：在 DS45-07 差异表补一行："旧路径以 `factor_dates ∩ prices_index` 确定日期，**必须改为按完整 grid 逐行计算、缺价置 NaN**"；在 DS45-05 增加一条硬约束："标签构造所用的价格面板必须逐行等于完整 grid（含 NaN 行），行数/索引不一致时以 `DatasetError(code=INVALID_DATASET)` 拒绝，而非静默取交集"；并新增一条 AC 断言：人为在价格面板中插入一个全 NaN 的 grid 行，断言该行产生缺失标签且候选分母不变（分母不减、损失不减）。
- **处置**：待处理。**必须修改**。

### REVIEW45-004 · `evaluation_id` 的"规范化配置"与"算法修订"没有可复算定义

- **定位**：[设计文档.md:227](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L227)、[设计文档.md:257](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L257)、[设计文档.md:268](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L268)
- **严重程度**：阻止基线确认
- **问题与影响**：`evaluation_id` 由 `dataset_id + 规范化评价配置 + fincore 算法修订` 共同决定，但两处都未定义：
  - **"规范化"未定义**：键序、浮点表示、`None` vs 缺省、`tuple` vs `list`、默认值是否显式展开参与哈希，全都没有规定。反例：`periods=[1,5,20]` 与 `periods=(1,5,20)` 若规范化不定义 → 同一配置得到两个 `evaluation_id`；若规范化过度展开（把隐式默认全部写入）→ "未声明 `preprocess`" 与 "显式声明 `preprocess='cross_section_rank'`" 得到两个 id。两种都破坏"改权重/方向/周期会生成新 evaluation_id"的单射语义——前者让等价的配置分裂，后者让等价的配置也分裂。
  - **"算法修订"未绑定来源**：是 fincore 的 git commit？package version？还是另设的算法修订串？设计文档:268 自己写了"同名 `0.5.1.dev0` 不能唯一确定功能"，但没有给出替代绑定。若用 commit，则同 commit 下未提交的本地改动无法区分；若用 version，则当前版本号根本不满足要求。

  这是全包里唯一直接影响"可复现性"承诺的缺口（DS45-03 provenance、DS45-09:257 都依赖它）。
- **建议**：在 DS45-09 补充两行可复算定义：
  - 规范化 = canonical JSON（键排序、UTF-8、无多余空白、float 用最短往返 repr、**缺省值先展开为默认值再参与哈希**、集合类字段排序后参与）；
  - 算法修订 = `fincore` git commit **加上** 参与计算的 `fincore/factor_analysis/*.py` 文件内容摘要；**禁止**单独用 package version 作为修订标识。

  并新增 AC：同一配置以 `list`/`tuple`、显式/隐式默认两种写法分别构造，`evaluation_id` 必须相等；改 `periods`/`direction`/权重任一项，`evaluation_id` 必须改变。
- **处置**：待处理。**必须修改**。

### REVIEW45-005 · fincore 异常体系与研究域四类异常之间没有映射合同

- **定位**：[设计文档.md:249](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L249)（异常类型与 code 枚举）、[设计文档.md:104](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L104)（"适配层负责结构映射和版本校验"）；fincore [exceptions.py:9-33](file:///D:/source_code/fincore/fincore/factor_analysis/exceptions.py#L9)
- **严重程度**：阻止基线确认
- **问题与影响**：fincore 现有异常体系是 `FactorDataError(ValueError)` 为基类，下挂 `EnhancedNonMatchingTimezoneError`、`FactorLossExceededError`，另有独立的 `MaxLossExceededError(Exception)`、`NonMatchingTimezoneError(Exception)`。而研究域要求的是 `ConfigError / DatasetError / DependencyError / DataQualityError` 四类 + 机器可读 code。

  映射缺口是实质性的，不只是命名不同：`FactorDataError(ValueError)` 既可能来自**索引/时区不匹配**（应映射 `DatasetError(code=MISSING_INPUT)`），也可能来自**参数非法**（应映射 `ConfigError(code=INVALID_CONFIG)`）。而 `FactorLossExceededError` 是 `FactorDataError` 的子类，在宽 except 下会被错误地归为 DatasetError；若再被 `except ValueError` 一把兜住，则 ConfigError 与 DatasetError 一起退化为空成功报告——而 DS45-08:242 恰恰明文禁止"不得被广泛 except 吞成空成功报告"。

  设计文档只说"适配层负责结构映射"，没说**映射表**，实施时几乎必然踩到这个坑。
- **建议**：在 DS45-08 增补一张**穷举映射表**（fincore 具体异常 → 研究域异常类型 + code），并明确三条实现纪律：(1) 适配层对每个 fincore 异常分支做**窄 except**，不得使用 `except ValueError` / `except Exception` 作为兜底；(2) 未映射的 fincore 异常**原样上抛**并标记为未分类错误，禁止静默降级为缺失值；(3) `FactorLossExceededError` 在映射层必须先被翻译成 `DataQualityError(code=LOSS_LIMIT_EXCEEDED)`，不得作为 `DatasetError` 泄漏。
- **处置**：待处理。**必须修改**。

---

## 三、实施前需澄清

### REVIEW45-006 · 新增 025/026 会让迭代 43 的复制出仓守卫变红，而回归范围没安排它

- **定位**：[验收方案.md:140-148](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L140)（§7.1 回归范围）、[验收方案.md:150-168](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L150)（§7.2）；[test_iteration43_copy_out_runnable.py:50-122](file:///D:/source_code/backtrader/tests/unit/test_iteration43_copy_out_runnable.py#L50)、[:314](file:///D:/source_code/backtrader/tests/unit/test_iteration43_copy_out_runnable.py#L314)（`test_every_tracked_main_entrypoint_is_classified`）；[test_iteration43_example_layout_boundaries.py:40](file:///D:/source_code/backtrader/tests/unit/test_iteration43_example_layout_boundaries.py#L40)
- **严重程度**：实施前需澄清
- **问题与影响**：迭代 43 的复制出仓守卫用**显式** `COPY_CONTRACT` 列表登记每个可复制叶子，并有一个测试把 git 追踪到的所有 example 主入口与已分类集合比对。新增 `examples/backtest/025_factor_single/run.py` 与 `026_factor_multi/run.py` 后，这两个叶子不在 `COPY_CONTRACT` 中 → `test_every_tracked_main_entrypoint_is_classified` **必然失败**。而在整份验收方案里 grep `iteration43|迭代43|copy_out|layout_boundaries`，**零命中**：迭代 45 的计划、需求、设计、验收从头到尾没有提及这条迭代 43 冻结守卫。

  更值得注意的是，验收方案 §7.2 明确要求"将整个例子目录复制到仓库外临时目录运行"——即迭代 45 **自己也要做复制出仓**，却没意识到仓库里已有一条同目的的守卫要求先把叶子登记进去。R7 收口时"全绿"会被这条守卫直接打红；更坏的情况是开发者为了让测试绿而放宽守卫。
- **建议**：在迭代计划 R7 与验收方案 §7.1 中显式加入两步：(1) 把 025/026 登记进迭代 43 的 `COPY_CONTRACT`（leaf + argv + 缺失输入标记，两个例子都依赖确定性生成器、无外部大文件，预计可直接标记为"缺失输入=None"）；(2) 把 `tests/unit/test_iteration43_copy_out_runnable.py` 与 `tests/unit/test_iteration43_example_layout_boundaries.py` 列入 §7.1 回归范围。备选方案：若这两个叶子本就不打算支持复制出仓，应显式给守卫增加"已登记不可复制"分类，而不是让它变成一条无法解释的红。
- **处置**：待处理。**必须修改**（验收方案 §7.1 + 迭代计划 R7 验收条件）。

### REVIEW45-007 · `QUANTILE_DEGENERATE` 缺少"重复边界导致组数 < q"的判别 fixture

- **定位**：[设计文档.md:189](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L189)、[设计文档.md:191](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L191)；[验收方案.md:77](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L77)（F-QCUT4）、[验收方案.md:192](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L192)
- **严重程度**：实施前需澄清
- **问题与影响**：`QUANTILE_DEGENERATE` 是 DS45-06/DS45-08 反复引用的关键 reason 码，其触发条件目前只有设计文档:189 的一句自然语言："重复边界、空组或无法形成 q 个非空组时"。而唯一相关 fixture F-QCUT4 覆盖的是"A 标签缺失、先分位后 mask"的**顺序**问题（A/B/C/D 分 q=2 两组），并不是退化路径。

  缺失的正是最容易实现错的分支：某截面只有 5 个不同取值、q=5 时 pandas `qcut` 可以切出 5 个非空组（每组 1 个）——这是**不均衡但可用**；而存在重复边界时只能形成少于 q 个非空组——这才是 `QUANTILE_DEGENERATE`。两者的区别恰好是"分位指标该输出还是该记 reason"，而实现者极易把"每组只有 1 个资产"误判为退化，从而丢掉本来可计算的 IC。
- **建议**：增补一条 fixture（如 `F-QCUT-DEGEN`）：同一截面含两个完全相等的分数且 q=5 → 断言该截面分位指标不可用、`reason=QUANTILE_DEGENERATE`；**同时断言同截面 IC 仍然有效**（落实 DS45-06:191）；再补一条"5 个不同取值、q=5、每组 1 个资产"的对照 fixture，断言分位指标**可用**。
- **处置**：待处理。**必须修改**（验收方案 §4 增补 fixture）。

### REVIEW45-008 · 分期损失口径自相矛盾：F-OOS"不计入任一段"与 DS45-08"不默默排除它再美化覆盖率"

- **定位**：[验收方案.md:86](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L86)（F-OOS）、[验收方案.md:184-186](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L184)；[设计文档.md:156](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L156)、[设计文档.md:238](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L238)、[设计文档.md:282](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L282)
- **严重程度**：实施前需澄清
- **问题与影响**：F-OOS 断言"跨段信号标签记 `SEGMENT_BOUNDARY` 并计入边界诊断，**不计入任一段**"；DS45-05:156 同口径（"跨段尾部标签剔除并单列"）；而 DS45-08:238 明确要求"分期单列边界损失，**不默默排除它再美化覆盖率**"。两句放在一起存在一个未被定义的自由变量：**分期的候选分母是"该段内的 eligible 候选行数"，还是"该段内信号与标签入口/出口都在段内的子集"**？

  两种读法的数值差异是实质性的（`next_open_to_open`、h=20、160/100 分段）：

  | 段 | 读法 A：分母=段内全部 eligible（边界损失计入） | 读法 B：分母=段内标签两端都在段内的子集（边界剔除） |
  |---|---|---|
  | development（160 bar） | 损失 21/160 = **13.13%** | 损失 0%，分母 139 |
  | validation（100 bar） | 损失 21/100 = **21.00%** | 损失 0%，分母 79 |

  读法 B 会让 validation 段报告"覆盖率 100%"，而实际上该段 21% 的 bar 悄悄消失——这正是设计文档:238 明令禁止的"美化覆盖率"。读法 A 则让 development/validation 的损失分别为 13.13%/21.00%，与 0.35 上限的关系需要逐段判定（当前均未超限，但没有规则说明），且一旦用户改 `periods` 加大 h 或缩短分段就可能超限。

  另注：DS45-05:156 的"段内信号与入口/出口均在段内才参与"是**参与资格**规则，不等于**分母**规则；当前文档把两者混在一句里，正是歧义来源。
- **建议**：在 DS45-05/DS45-08 明确三件事：(1) 分段候选分母 = 该段内、该 group、universe=true 的**全部** eligible 候选行数（读法 A）；(2) 跨界剔除的 bar **计入该段损失分子**，另单列 `SEGMENT_BOUNDARY` 计数（不排除出分母）；(3) 明确 `SEGMENT_BOUNDARY` 的两类来源要分开计数——"跨段尾部（出口落入下一段）"与"段内无未来标签（出口越出研究区间/段末）"。然后在 F-OOS 中把断言改成可判定的数值：`development` 段 h=20 的可评价 bar 数与损失占比、`validation` 段同理，写死期望值而不是"检查是否超过 max_loss"。
- **处置**：待处理。**必须修改**（设计文档 DS45-05/08 + 验收方案 F-OOS 断言具体化）。

### REVIEW45-009 · 预热窗口与研究区间起点的关系未定义

- **定位**：[设计文档.md:116](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L116)、[设计文档.md:126](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L126)、[设计文档.md:134](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L134)、[设计文档.md:238](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L238)
- **严重程度**：实施前需澄清
- **问题与影响**：`grid` 含预热、`raw_factors` 只含研究区间（DS45-03:126），但"研究区间起点相对 grid 起点的偏移量"没有定义规则。一个 20-bar 的 Indicator 需要 20 个观察 bar 才有值（DS45-04:134 明说单输入 period 遵循"该 Feed 已观察 bar 数"语义），所以**若研究区间从 grid 第 0 行开始，其前 20 个 bar 的因子必然为 NaN**，按 DS45-08:238"用户研究区间内的未预热样本纳入损失"，这 20 个 bar 全部计入损失分子。DS45-10:282 说示例有"充分预热"，但那是示例约定，不是通用约束。

  反例：某次研究把 ROC 的 period 调到 60，或某资产晚 30 个 bar 上市（DS45-04:134 允许晚开始资产参与），研究区间前若干 bar 就是 NaN；这些损失是"预热未完成"而非"数据质量缺陷"，与 REVIEW45-001 的标签尾部属于同一类结构性问题。
- **建议**：明确两条：(1) **构造约束**——研究区间起点必须 ≥ 全体目标资产的最长 Indicator 预热窗口；不满足时在采集阶段按 `DatasetError(code=INVALID_CONFIG)` 拒绝，而不是让损失统计去承担；(2) 记录一个与 `NO_CURRENT_BAR`（DS45-04:132）并列的 reason（如 `NOT_READY`）表示"预热窗口未满"，并规定它是否计入 max_loss 分子。
- **处置**：待处理。**必须修改**（设计文档 DS45-03/04/08 增补）。

### REVIEW45-010 · 研究域依赖分层没有规定 3.8/3.10 的失败形态

- **定位**：[设计文档.md:261-266](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L261)（依赖分层表）、[验收方案.md:144-148](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L144)
- **严重程度**：实施前需澄清
- **问题与影响**：依赖表规定"既有 `import backtrader` / 普通回测保持核心声明的 Python 3.8+；研究域以 Python 3.11+ 作为本轮支持范围"，但没有规定 3.8/3.10 下 `import backtrader.research` 的**具体失败形态**。两个真实风险：
  1. 有人在核心 `backtrader/__init__.py` 加了研究域的延迟导入 → 3.8 环境 `import backtrader` 直接失败，这会破坏仓库既有的"核心 3.8+ 可用"承诺，且只在 3.8 环境才暴露；
  2. 3.10 下若研究域用了 3.11 语法（`except*`、新类型别名等），抛出的是 `SyntaxError` 而非 `DependencyError`；若 pandas 版本不满足，抛的是 `ImportError`。调用方无法用统一方式判别，DS45-08:249 的 `DependencyError(code=DEPENDENCY_UNAVAILABLE)` 形同虚设。

  验收方案 §7.1 也没有为 3.8/3.10 环境安排任何断言。
- **建议**：在 DS45-09 依赖表增补："Python < 3.11 下 `import backtrader.research` 必须抛 `DependencyError(code=DEPENDENCY_UNAVAILABLE)`（或一个明确声明为该类型的 ImportError 子类），不得抛裸 `SyntaxError`/`ModuleNotFoundError`"；并加两条 AC：(1) 在 3.8 环境 `import backtrader` 成功，且 `sys.modules` 中不含 `pandas`/`fincore`；(2) 在 3.10 环境 `import backtrader.research` 抛 `DependencyError`。
- **处置**：待处理。**必须修改**（设计文档 DS45-09 + 验收方案增补 AC）。

### REVIEW45-011 · 20 资产 × q=5 时每组仅约 4 个资产，`min_quantile_assets=1` 使分层输出无统计意义

- **定位**：[设计文档.md:282](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L282)（示例规模）、[设计文档.md:88](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L88)（默认 `min_quantile_assets=1`）；[验收方案.md:172](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L172)
- **严重程度**：实施前需澄清
- **问题与影响**：20 个资产、q=5 → 每组平均 4 个资产；单日组内均值几乎等同于单个资产的收益，"最高组减最低组"被个体噪声主导。默认 `min_quantile_assets=1` 允许把这些均值原样输出。

  计划本身是诚实的——DS45-10:286 说"不要求 IC 为正或利润达到阈值"，验收方案:172 说"生成数据的 IC 正负皆可"。但诚实的范围是"不设收益门槛"，**没有**声明"当前规模下分层数字不具统计解释力"，读者极易把示例输出里的 spread 当作因子强弱证据。
- **建议**：二选一，均不扩大范围：(a) 把示例规模提高到每组 ≥ 20 个资产（即 ≥ 100 资产），使分层统计具备最低可解释性；(b) 保持 20 资产，但在示例 README 与输出中显式标注每组样本量下限，并把示例自己的 `min_quantile_assets` 设到 3 或 5，让示例**本身演示"小样本不输出"这条分支**（正好覆盖 DS45-06:189 的缺失语义）。
- **处置**：待处理。**建议修改**（示例参数与说明澄清，不改范围）。

### REVIEW45-012 · `comparisons` 的 common 池构造措辞可读出两种互斥结果

- **定位**：[设计文档.md:89](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L89)、[设计文档.md:177-183](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L177)；[验收方案.md:83](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L83)（F-MULTI-COMPARISON）
- **严重程度**：实施前需澄清
- **问题与影响**：DS45-06:180 写"取成员并集所需的有效资产交集"。这句话可以读成两种意思：
  - 读法 1（交集的并集）：每个信号各自取"自己所有成员都有限"的集合，再把这些集合**并起来**；
  - 读法 2（并集的交集）：把该 comparison 下所有信号的**全部成员**放进同一个池，要求所有成员都有限，取这个池。

  两者的共同资产集合不同，直接改变 `paired_period_count` 和 `delta_IC`——而这两项正是"公平比较"的核心产出。F-MULTI-COMPARISON 只覆盖了一个具体数值（共同池 A/B、形成损失 2/4），无法证伪另一种读法。

  另有一个相关歧义：基础因子作为**独立信号**进入 common 池时，是否也要求"该因子自身在 common 池内被重新变换"（DS45-06:177 说要重新变换），还是沿用 own 池的变换值。
- **建议**：用一行公式替代表述，并明确基础因子的处理：(1) 写明 common 池的资产集合 = 所有被列信号的**全部成员在该截面上均有限**的资产集合（即读法 2，明确"池是信号的并集，筛选条件是并集内全部有限"）；或明确选读法 1；(2) 明确"基础因子在该池内重新变换，且其 own 池报告仍单独保留"；(3) 增补一条 fixture，用两个成员集合不同的组合断言共同池资产集合的**具体名单**，而非仅断言一个损失比例。
- **处置**：待处理。**建议修改**（设计文档 DS45-06 措辞精确化 + 验收方案增补断言）。

---

## 四、可选建议

### REVIEW45-013 · `evaluation_id` 之外建议另存裸配置摘要

- **定位**：[设计文档.md:227](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L227)
- **严重程度**：可选建议
- **问题与影响**：`evaluation_id` 是不透明摘要，人工比对两次评价是否同配置时无法反解。
- **建议**：manifest 另存 `evaluation_config_sha256`（规范化配置的裸摘要）与 `fincore_algorithm_revision` 两个可读字段，与 `evaluation_id` 并存。属于 manifest 增字段，不改语义。
- **处置**：待处理。可选。

### REVIEW45-014 · 缺 `ZERO_IC_STD` 与"IC 恒为 0"的 fixture

- **定位**：[设计文档.md:249](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L249)、[验收方案.md:75](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L75)（F-ICIR3）、[验收方案.md:192](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L192)
- **严重程度**：可选建议
- **问题与影响**：F-ICIR3 覆盖的是 IC=(-0.5, 0, 0.5) 的正常情形（std=0.5，ICIR=0）；`ZERO_IC_STD` 这条 reason 没有对应 fixture。验收方案:192 写了"常数 IC/零标准差 IR 不造 0"，但"IC 序列恒为 0（std=0）"与"IC 序列常数非零（std=0）"两种退化没有区分断言——前者 ICIR 严格无定义，后者同样是零标准差。
- **建议**：增补一条 fixture：IC 序列恒为同一非零值 → `std=0` → ICIR **缺失**、`reason=ZERO_IC_STD`（不得输出 0），且该 slice 仍可输出 IC 均值与正值占比。
- **处置**：待处理。可选（建议补）。

### REVIEW45-015 · 建议在 §7.2 增加"尾部与分段损失"的显式期望值断言

- **定位**：[验收方案.md:150-168](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L150)
- **严重程度**：可选建议
- **问题与影响**：§7.2 只给出门槛（20 资产/260 bar/21-bar 尾部/160-100 分段）和"非空统计"，没有把 REVIEW45-001/008 讨论的尾部与边界损失写成期望值，示例验收无法发现口径漂移。
- **建议**：在 §7.2 增加：完整研究期 h=20 的可评价 bar 数与损失占比；development/validation 两段各自的可评价 bar 数、边界损失计数与 `SEGMENT_BOUNDARY` 计数（具体数值依 REVIEW45-008 的口径结论确定后写死）。
- **处置**：待处理。可选（建议补，且依赖 REVIEW45-001/008 的结论）。

### REVIEW45-016 · `PARTIAL` 状态对应的退出码未明确

- **定位**：[设计文档.md:251](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L251)、[验收方案.md:190-192](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/验收方案.md#L190)
- **严重程度**：可选建议
- **问题与影响**：退出码定义"0=必需输出可用且验收通过，1=计算、数据或验收失败"，结果状态定义 OK/PARTIAL/UNEVALUABLE。`PARTIAL`（有有效结果但部分指标退化）落到哪个退出码没有写。`UNEVALUABLE` 已明确"不得以 0 表示通过"，`PARTIAL` 没有对应表述。
- **建议**：明确 `PARTIAL` 的退出码（建议：库层返回 PARTIAL 且 CLI 退出 0 但**必须**在 stderr/manifest 中标记；或退出 1 取决于"必需输出"是否包含退化项——需在验收方案中写死），并加一条 AC。
- **处置**：待处理。可选（建议在实现前定死）。

### REVIEW45-017 · 建议明确 `qcut` 在 `quantiles > 可用不同值数` 时的行为与 reason 归属

- **定位**：[设计文档.md:189](file:///D:/source_code/backtrader/docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/设计文档.md#L189)
- **严重程度**：可选建议
- **问题与影响**："无法形成 q 个非空组时…记录 `QUANTILE_DEGENERATE`"覆盖了这一情形，但 pandas `qcut` 在该情形下默认抛 `ValueError`（"Bin edges must be unique"），与 fincore 现有 `no_raise` 路径（data.py:379）的关系也需要说清：新入口应当**捕获并转成 reason**，而不是让 pandas 的 `ValueError` 冒泡——后者会命中 REVIEW45-005 讨论的宽 except 风险。
- **建议**：在 DS45-06/DS45-08 增补一句："`qcut` 的分组失败必须被捕获并转为 `QUANTILE_DEGENERATE`，不得以 `ValueError` 形式泄漏到研究域异常层"，并纳入 REVIEW45-007 的 fixture 断言。
- **处置**：待处理。可选（建议补）。

---

## 五、复核通过的部分（供采信）

以下为逐条复算/比对后确认**准确无误**的部分，可直接作为基线采信依据：

- **全部 17 条验收 fixture 的手算预期全部吻合**（F-RANK4 的平均秩 (−1,0,0,1)、F-Z3 的 ±√(3/2)、F-IC3 的 Pearson 4√3/7 ≈ 0.989743318610787 且 Spearman=1、F-ICIR3 的 ICIR=0 与 positive fraction 1/3、F-BAR4 的 0.1 / 1/11 / 2/11、F-COMMON 的 common 池 A/B/C 与 formation loss 1/4、F-FUTURE 的 2/11→119/11、F-ORDER 的 B<C<A vs A<B<C、F-MULTI-COMPARISON 的共同池 A/B 与形成损失 2/4）。容差 `math.isclose(abs_tol=1e-12, rel_tol=1e-10)`（验收方案:91）是合理的。
- **DS45-07 差异表四条已有断言全部与 fincore 源码相符**：固定 Spearman（`performance.py:72,95`）、`include_portfolio_inputs=True`（`analysis.py:395,741`、`models.py:1474`）、旧分位换手按"出现该分位的日期"迭代（`analysis.py:194-210`）、`analyze_factor` 是单表清洗流程。**该表的其余条目也准确**——问题只在于漏了两条（见 REVIEW45-002/003）。
- **两仓顺序**（fincore 先提交、Backtrader 再接入）、**不改历史指标默认值迁就示例**（DS45-10:279）、**拒绝把"分位退化"传播为"IC 不可用"**（DS45-06:191）、**拒绝跨组混合 IC 与跨币种组合收益**（DS45-03:126）、**拒绝用未受控 p 值选方向**（DS45-07:206）、**Broker submit/cancel 计数器作为无下单证据**（AC45-01）——这些都写得很扎实，是同类方案里少见的严谨。
- **fincore 依赖分层与"核心 3.8+ 不受研究域影响"的意图**（DS45-09:261-266）方向正确，只是缺失败形态断言（REVIEW45-010）。
- **DS45-10:288 的"评审中需要确认的决定"清单**列出的七项（严格 closed-bar 时钟、多输入完整网格、正价简单收益、qcut 不拆 ties、分位失败保留 IC、共同池形成损失与 max_loss、bar 单位、依赖分层）确实是本轮最需要外部意见的地方，同意"不应留到开发时临时决定"这一判断。

---

## 六、基线确认前的最小回答清单

若要把这轮方案标记为"已接受基线"，建议至少需要下面 8 条被明确回答（可以只在文档里补写，不必改代码）：

1. `max_loss` 的分母是否排除标签结构性尾部？若否，可行研究长度下界公式是什么？（REVIEW45-001）
2. 复用 fincore 现有 `prepare_factor_data_by_horizon` 时，loss 口径与 `no_raise` 行为如何与 DS45-08 对齐？（REVIEW45-002）
3. 新标签路径如何在完整 grid 上逐行计算（含 NaN 行），而不是取交集？（REVIEW45-003）
4. `evaluation_id` 的规范化规则与"算法修订"的绑定源分别是什么？（REVIEW45-004）
5. fincore 各异常 → 研究域四类异常 + code 的完整映射表。（REVIEW45-005）
6. 分期（segments）的候选分母与边界损失口径是什么？F-OOS 与 DS45-08 的冲突如何裁定？（REVIEW45-008）
7. 025/026 是否登记进迭代 43 的复制出仓 `COPY_CONTRACT`，且该测试列入 §7.1 回归范围？（REVIEW45-006）
8. 3.8/3.10 环境下 `import backtrader.research` 的失败形态与 `DependencyError` 契约。（REVIEW45-010）

---

## 七、审阅方法附注

- 本次审阅**未运行任何测试、未执行任何 AC**：22 条 AC 状态仍全部为 `NOT_RUN`，本次结论不改变其中任何一条的状态。
- fincore 侧只做**只读源码比对**，未改动 `D:/source_code/fincore` 任何文件；引用的行号均来自 `dev@2354bb560788f372502151a8b1b53accf536a6c0`。
- 全部损失/收益算术（21/260、21/160、21/100、21/60、21/59、13.13%、21.00%、35.00%、35.59%）为按 DS45-05/DS45-08 公式手工推导，未依赖任何未实现的代码。
- 未读取任何私有输入（`.env`、真实 `config.yaml`、凭据），未做任何网络访问。
- 本报告只创建了本文件，**未修改需求/设计/验收/计划/README 任何内容，未提交任何 commit**。

---

**模型署名**：本报告由 **MiniMax-M3.1-Flash** 独立生成。

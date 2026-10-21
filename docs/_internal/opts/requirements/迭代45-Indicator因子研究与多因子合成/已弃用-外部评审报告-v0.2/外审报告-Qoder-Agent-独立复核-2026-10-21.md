# 迭代 45 外审报告（独立复核）

- 报告编号：REVIEW45-OR-2026-10-21
- 审阅对象：`README.md`、`需求文档.md`、`设计文档.md`、`验收方案.md`、`迭代计划.md`
- Backtrader 基线：`D:/source_code/backtrader`，`dev`，HEAD `8457e8a53cec879a48de079b3da9c7f56ccece41`
- fincore 基线：`D:/source_code/fincore`，`dev`，HEAD `2354bb560788f372502151a8b1b53accf536a6c0`（工作区干净，版本 `0.5.1.dev0`，`requires-python >=3.11`）
- 审阅者：Qoder Agent
- 大模型标识：按 Qoder 运行约束不披露底层模型名称；本报告以 “Qoder Agent” 署名。
- 审阅日期：2026-10-21
- 审阅方式：只读通读五份文档；对照 Backtrader/fincore 源码与运行时行为逐项核验；手算复核统计 fixture；检查 BOM、交叉链接和 Git 交付状态。未读取同目录其他未跟踪审阅稿，未修改方案、代码或 fincore 工作区。
- 结论：**有条件通过。方案的需求—设计—验收分层、统计口径和跨仓顺序总体扎实；但在 4 个阻断项修订前，不建议将文档冻结为基线或启动 R1。阻断项主要是事实性与合同性澄清，不需要扩大功能范围。**

---

## 1. 审阅范围与方法

### 1.1 实际核查的输入

- 五份 Markdown 均已由 `8457e8a53` 跟踪提交；五个文件均带 UTF-8 BOM；文档内相对文件路径链接均可解析（锚点未做渲染验证）。
- 方案 §2 记录的 Backtrader 快照 `57b572ed8…` 是计划编写时基线；当前 HEAD 为审查包提交 `8457e8a53…`，两者关系在 README/计划中有说明，不构成矛盾。
- fincore 只读基线 `2354bb56…` 与方案一致；`git status` 为空，`fincore.__version__ == 0.5.1.dev0`，`pyproject.toml` 声明 `requires-python = ">=3.11"`。
- 本轮没有运行账户、网络、真实 provider 或认证测试；没有执行功能验收，符合“本轮仅文档”的范围声明。

### 1.2 核查方法

1. 对方案中“现有行为/现有接口”的每条声明，定位到具体源码并核对默认值与执行路径。
2. 对统计 fixture 做手算复核，确认期望值能区分正确与错误实现。
3. 做少量只读运行时探针：`import backtrader` 的依赖加载、KDJ/ROC/SMA 的最小周期、KDJ 零振幅行为、现代 `runonce` 的时钟驱动方式。
4. 检查验收矩阵是否覆盖设计中声明的每一条关键合同，而不是只检查“有一个结果”。

### 1.3 独立性说明

同目录存在其他未跟踪审阅稿。本报告未读取、未引用这些文件；以下结论均由五份文档、源码证据和手算独立得出。

---

## 2. 已核实为正确的关键事实

| 方案声明 | 实证结果 | 结论 |
|---|---|---|
| fincore 本地 dev 基线为 `2354bb56…`，版本 `0.5.1.dev0`，Python >=3.11 | `git rev-parse HEAD`、`fincore.__version__`、`pyproject.toml:15` 均一致 | 正确 |
| fincore 的 IC 当前固定为 Spearman | `performance.py:95` 使用 `method="spearman"` | 正确 |
| `include_portfolio_inputs` 默认 True，需要显式关闭 | `analysis.py:395,741`、`models.py:1474` | 正确 |
| 既有换手按“实际出现该分位的日期”迭代 | `performance.py:290-323` 只遍历该分位出现的日期 | 正确 |
| 预计算多列入口会先共同 `dropna` | `data.py` 的 `_prepare_from_forward_returns` 在 quantize 前 `merged.dropna()` | 正确 |
| 价格路径 `prepare_factor_data_by_horizon` 支持分周期、先分位后标签 | `data.py:441` 起先对有限因子分位，再逐 horizon 过滤 | 正确，但有重要边界，见 REVIEW45-005 |
| `mean_return_by_quantile` 默认 `demeaned=True` | `performance.py:356-361` | 正确；方案要求显式 False 是必要的 |
| `fincore.factor_analysis.analysis` 不导入绘图库 | 模块 docstring 与导入清单确认；绘图在 `tears.py`，通过可选模块加载 | 正确 |
| 现有 KDJ 的 SMA 变体、`J=3K-2D`、第 13 个观察 bar 起有效 | `stochastic.py:214`、`shared_strategy_indicators.py:1243-1299`；运行时 `_minperiod == 13` | 正确 |
| KDJ 零振幅窗口为缺失 | 运行时零振幅输入得到 `K=D=J=NaN` | 与设计的“窗口分母 0 为缺失”一致 |
| 现有 ROC 在分母为 0 时返回 0.0 | `momentum.py` 的 `next()`/`once()` 均显式写 0.0；`_minperiod == 21` | 正确；也证明示例需要包装层，方案已预见到 |
| 025/026 示例编号当前空闲，且 `examples/backtest` 采用四件套标准 | 现有目录为 001–024 的非连续占用；`examples/README.md:14-15` 定义 `README.md + config.yaml + <name>_strategy.py + run.py` | 正确 |
| 现代 `_runonce` 会取所有 feed 的最小下一时点，而不是只用首个 feed 的长度 | `_cerebro/runonce.py:101-116` | “首个 Feed 提前结束不能丢掉其他资产后续观测”在实现上可行 |
| 统计 fixture 的数值期望正确 | F-RANK4、F-Z3、F-IC3、F-ICIR3、F-BAR4、F-QCUT4、F-COMMON、F-ORDER、F-MULTI-COMPARISON、F-FUTURE 均逐项手算复核 | 正确，见 §2.1 |

### 2.1 手算复核结论

- F-RANK4：平均秩 `(1, 2.5, 2.5, 4)`，标准化后 `(-1, 0, 0, 1)`；方向 `-1` 取反正确。
- F-Z3：`(1,2,3)` 的总体标准差为 `sqrt(2/3)`，z 值为 `±sqrt(3/2)`，正确。
- F-IC3：`x=(1,2,3)`、`y=(1,4,9)` 的 Pearson 为 `4√3/7 ≈ 0.989743`，Spearman 为 1；对 x 做 rank 变换后 Pearson 仍为 `4√3/7`，正确，且能区分“把 Pearson(rank(x),y) 当成 Rank IC”的错误实现。
- F-ICIR3：`(-0.5, 0, 0.5)` 的均值 0、样本标准差 0.5、ICIR 0、正值占比 1/3，正确。
- F-BAR4：close-to-close h=1 为 `0.1`；next-open h=1 为 `1/11`；h=2 为 `2/11`，正确。
- F-QCUT4：先对 `(1,2,3,4)` 分两组，再应用 A 的标签缺失，B 留在低组；若先删 A 再 qcut，C 会落入低组，正确说明了顺序差异。
- F-COMMON、F-ORDER、F-MULTI-COMPARISON、F-FUTURE 的排名、权重、共同池损失和未来扰动方向均正确。

这些 fixture 本身质量较高，能够证伪常见实现错误；这是本方案最强的部分之一。

---

## 3. 阻止基线确认的问题

### REVIEW45-001 依赖边界与当前打包/导入事实冲突

- **定位**：需求文档 §6.2；设计 DS45-09 环境分层表；验收 AC45-16；迭代计划 §4。
- **严重程度**：阻止基线确认。
- **实证**：
  - `backtrader/setup.py:53-71` 的 `install_requires` 明确包含 `pandas>=1.3.0` 和 `matplotlib>=3.3.0`。
  - 在本机执行 `import backtrader` 后，`pandas` 已出现在 `sys.modules`；`matplotlib` 未加载，`fincore` 未加载。
  - `backtrader/setup.py:109` 仍声明 `python_requires=">=3.8"`。
- **问题与影响**：需求文档写“Backtrader 核心导入和普通回测不依赖研究域、pandas、fincore 或图形后端”，DS45-09 写“pandas 等依赖局部加载”“PNG 再按显式请求加载可选绘图依赖”。就当前仓库而言：
  - pandas 是必需安装依赖，并且核心导入已经加载；
  - matplotlib 是必需安装依赖，“可选”只对运行时导入成立，不对安装成立；
  - AC45-16 只验证“无 fincore”的核心导入、研究环境以及绘图的延迟加载，不验证“无 pandas / 无 matplotlib 安装”，因此不会发现这个偏差。
  这会让读者误以为存在“无 pandas / 无 matplotlib 的核心安装”，也可能诱导实现者在本迭代顺手修改打包依赖，造成范围外回归。
- **建议**：将表述改为“本轮不改变现有必需依赖；fincore 为评价阶段的可选运行时依赖；图表模块延迟导入；pandas/matplotlib 仍随包安装”。如果确实要把 pandas/matplotlib 变为可选依赖，应另立打包轮次，并补充全量核心回归，不建议纳入本轮。
- **处置**：待处理。
- **范围影响**：只需修订文字与 AC 分层，不新增功能；若真要改打包依赖，则属于新范围。

### REVIEW45-002 研究 grid、calendar 与 source_timezone 的构造/声明合同缺失

- **定位**：设计 DS45-02 的 `ResearchSpec` 字段、DS45-03 的 grid 不变量、需求 §2 的用户流程第 1 步、DS45-10 示例中的 `closed_bar_grid`。
- **严重程度**：阻止基线确认。
- **实证**：
  - `ResearchSpec` 要求 `grid/start/end/targets/source_timezone/snapshot_id/price_basis`，但没有 `calendar`/`calendar_id` 字段；`grid` 是用户传入的对象，方案没有给出公开构造器，示例中的 `closed_bar_grid` 没有定义。
  - 设计要求 grid 的 `open_time/close_time`“必须来自声明日历”，但 `open_time` 不能总是由 `close_time` 推导；例如夜盘日线的 open_time 与前一日收盘/当日开盘的关系取决于交易所 session 日历。
  - `source_timezone` 是一个标量，但方案没有说明每个 Feed 的原始时间是 naive 还是 aware、是否都使用同一个源时区。Backtrader 的 `num2date(x, tz=None, naive=True)`（`backtrader/utils/dateintern.py:373`）默认返回 naive UTC；`data.datetime` 是数值时间线，模板无法通用地反推原始来源时区。
  - 设计明确警告“不能给已是 UTC 的时间二次本地化”，但没有给出判断/声明机制。
- **问题与影响**：本轮最核心的合同是“一次 run 只有一个可比的研究 grid”。当前接口让用户手写一个符合内部 UTC 数值语义的 grid，且无法从声明中验证该 grid 与 Feed 是否同源、同时区、同 session 收盘。结果是：
  - 用户可以使用错位的 grid 或错误的 `source_timezone`，得到“看似成功”的采集；
  - 不同用户对日线 close_time 的理解不同（00:00、15:00、夜盘收盘等），示例之外的可用性差；
  - 适配层无法稳定判断“naive 输入”与“已是 UTC”的差别，违反方案的 PIT/时钟正确性目标。
- **建议**：在 R1 冻结以下合同：
  1. 增加 `ResearchSpec.calendar`（或 `calendar_id`）与 session 定义；
  2. 提供公开的 `build_closed_bar_grid(feeds, calendar, source_timezone, ...)` 或 `ResearchSpec.from_feeds(...)`，由它生成并验证 `open_time/close_time`；
  3. 明确 Feed 时间声明：要么要求所有参与 Feed 已是 UTC/统一的 naive 约定，要么增加逐 Feed 的 `FeedTimeSpec`（原始时区、naive/aware、bar 时间戳代表 open 还是 close）；
  4. 在绑定阶段校验 grid 与 Feed 时间线一一对应、无重复/无歧义；
  5. 增加 naive vs UTC、session 收盘、重复时间戳、跨时区 data set 的已知答案 fixture。
- **处置**：待处理。
- **范围影响**：增加一个构造/校验入口与若干字段，仍在本轮“研究 grid/时钟”范围内；不改变统计范围。

### REVIEW45-003 离线方向覆盖在 EvaluationSpec 与验收中缺失

- **定位**：设计 DS45-02 的 EvaluationSpec 字段表与“方向可在离线评价时通过已记录的 EvaluationSpec 显式覆盖”一句；需求 REQ45-04；验收 AC45-15。
- **严重程度**：阻止基线确认。
- **实证**：
  - EvaluationSpec 字段表列出 `periods/label/quantiles/min_assets/min_quantile_assets/preprocess/max_loss/combinations/comparisons/segments`，没有方向覆盖字段。
  - AC45-15 只要求“改权重/周期不调用 Cerebro 或 Indicator”，没有方向覆盖用例。
  - 方案同时要求“输出同时记录原始声明和本次覆盖”，但没有定义覆盖字段名、校验和结果位置。
- **问题与影响**：REQ45-04 明确把“方向”列为可离线调整的评价配置；DS45-02 也重复了这一能力。如果实现者只实现周期/权重复评，方向覆盖会成为缺失能力；如果自行发明字段，又会与验收文档脱节。这是典型的“需求—设计—验收三份文档不一致”。
- **建议**：在 EvaluationSpec 增加显式的 `direction_overrides`（因子名→+1/-1）或 `directions`，规定只允许已存在因子、拒绝 bool、只接受 +1/-1；在 manifest/结果中同时记录原始 FactorSpec 方向和本次有效方向；在 AC45-15 增加“仅改方向后离线复评，结果方向翻转/统计相应变化，且不重新采集”的断言。如果决定不提供该能力，则应删除 REQ45-04 中的“方向”措辞并说明原因。
- **处置**：待处理。
- **范围影响**：小；不新增算法，只补配置与验收。

### REVIEW45-004 验收矩阵未覆盖若干已声明的关键合同

- **定位**：AC45-05、AC45-14、AC45-17、AC45-03；设计 DS45-04/08/09。
- **严重程度**：阻止基线确认。
- **问题与影响**：以下合同已写入设计，但没有可执行断言；由于本轮“完成”定义为 22 项 AC 全部 PASS，这些漏洞会使“全部 PASS”不能证明合同成立：
  1. **PARTIAL 状态**：AC45-14 只列了退化/全缺失；F-ALL-MISSING 覆盖 UNEVALUABLE，没有“一个有效信号 + 一个退化/不可用信号 → PARTIAL”的 fixture。`OK/PARTIAL/UNEVALUABLE` 是 DS45-08 的核心结果状态，必须至少有一个 PARTIAL 正例/反例。
  2. **tick 与 resample 不支持**：DS45-04 和计划 §1 明确包含 tick、resample；AC45-05 只列 Replay/live/mixed-timeframe，F-MULTI-GAP 只写“错时钟”。需要显式 tick 与 resample 的 `UNSUPPORTED_CLOCK` 负例。
  3. **方向覆盖**：见 REVIEW45-003；AC45-15 未覆盖。
  4. **JSON null/CSV 空字段**：DS45-08 要求 JSON 不出现 NaN/Infinity 字面量、CSV 缺失为空字段；AC45-17 只写“可读且字段一致”，没有 `allow_nan=False` 或空字段断言。
  5. **覆盖写拒绝**：DS45-09 要求数据集/结果默认写新目录、拒绝覆盖已有交付；AC45-15/17 没有该负例。
  6. **同一键不同值冲突**：DS45-04 要求“相同键不同值报冲突”；AC45-03 只覆盖重复通知只采一次，没有不同值冲突用例。
- **建议**：为上述六项各加一个最小 fixture/断言，并映射到现有 AC（或新增子断言）：F-PARTIAL、F-CLOCK-TICK、F-CLOCK-RESAMPLE、F-DIRECTION-OFFLINE、F-JSON-NONFINITE、F-OVERWRITE、F-DUP-KEY。保持 AC 编号总数不变，作为 AC45-03/05/14/15/17 的子断言。
- **处置**：待处理。
- **范围影响**：仅补验收，不新增产品能力。

---

## 4. 实施前需澄清的问题

### REVIEW45-005 fincore 现有 `prepare_factor_data_by_horizon` 与新合同的复用边界未冻结

- **定位**：设计 DS45-02 “可复用现有 `prepare_factor_data_by_horizon`…”；DS45-06/07/08 的分位独立、`max_loss` 与损失分母。
- **严重程度**：实施前需澄清（高）。
- **实证**：
  - `data.py:441` 的价格路径确实先对有限因子分位，再逐 horizon 处理，符合“先分位后标签”；
  - 但 `data.py:526` 对每个 horizon 执行 `dropna(subset=["factor_quantile"])`，分位退化/失败的日期会被整行删除；
  - `data.py:321-335` 的 `_loss_report.total_loss = factor_loss + forward_loss + binning_loss`，把分位损失计入 `max_loss`；
  - `data.py` 的 `_prepare_from_forward_returns` 在 quantize 前先 `merged.dropna()`，预计算路径仍是共同缺失过滤。
- **问题与影响**：如果 R1 直接复用 `PreparedFactorData.data` 作为 IC/分层输入，会同时违反两条设计：
  - 分位失败会删除本可计算的 IC（违反 DS45-06/08“分位失败不抹除合法 IC”）；
  - 旧 `total_loss` 把分位损失计入 `max_loss`，与 DS45-08“分位损失另以有限配对数为分母、不重复计入上限”不一致。
  方案虽然提出“新编排与缺失语义仍在 fincore”，但没有在 DS45-07 的差异表中把这两点列为必须新增/不能复用的边界。
- **建议**：在 R1 明确：
  1. `prepare_factor_data_by_horizon` 保留为兼容/参考叶模块，不能作为新 IC 路径的唯一数据源；
  2. 新增公开 `prepare_factor_signals`，分别返回“因子+标签配对（与分位无关）”“分位标签”“分位退化信息”；
  3. 新增与新合同一致的损失报告字段，`max_loss` 只使用候选→有限信号+标签配对损失，分位损失单列；
  4. 为旧 API 的默认行为加兼容回归，避免为满足新合同而静默改变旧语义。
- **处置**：待处理。
- **范围影响**：仍在本轮 fincore 新增分析能力的范围内；只是把复用边界写清楚。

### REVIEW45-006 fincore API 能力/版本检查缺少可执行定义

- **定位**：设计 DS45-09 “准确检查 API 能力及实际模块来源”；验收 AC45-13/16/22。
- **严重程度**：实施前需澄清（中高）。
- **问题与影响**：fincore 版本为 `0.5.1.dev0`，方案明确说“同名 0.5.1.dev0 不能唯一确定功能”。AC45-13/22 通过记录 wheel 哈希、commit 和 import path 来证明集成来源，但 Backtrader 运行时没有定义的“能力检查”：
  - 若环境里装的是旧 dev wheel，仍可 import 同名包，但缺少新函数或旧函数语义不同；
  - 可能直到评价阶段才 `AttributeError`，而不是在适配层以 `DependencyError(DEPENDENCY_UNAVAILABLE)` 快速失败；
  - wheel 哈希是证据，不是运行时检测。
- **建议**：增加 fincore 模块级 API 能力版本（例如 `FACTOR_RESEARCH_API_VERSION` 或 `capabilities()` 返回函数名/语义版本），为本次新增 API 升一次 fincore 版本；Backtrader adapter 在导入后、任何评价前检查能力并抛出 `DependencyError`；把该检查纳入 AC45-13/16/22。
- **处置**：待处理。

### REVIEW45-007 二级 Feed 时钟回归应在本轮强制，而不是仅在“修改核心 clock/minperiod”时执行

- **定位**：迭代计划 §5 的回归策略；R1/R2；设计 DS45-04。
- **严重程度**：实施前需澄清（中高）。
- **问题与影响**：`AGENTS.md` 明确把“多数据/二级 Feed 时钟”列为高 bug 风险区。`FactorStrategy` 会按目标资产创建 Indicator，并为多输入因子绑定目标 Feed + 基准 Feed；即使不修改核心代码，这也直接使用了二级 Feed 时钟路径。计划目前只在“修改核心 clock/minperiod”时要求 `make test-strategies`；这会导致：
  - R1/R2 的定向 runonce/runnext 用例通过，但已有的多数据策略回归被跳过；
  - 一旦新模板暴露或改变 `_resolved_secondary_clock` 行为，问题可能到示例或后续轮次才出现。
- **建议**：R1 和 R2 的退出条件中明确执行 `make test-strategies`（或至少执行其中多数据/指标时钟相关子集），记录完整结果；若担心耗时，可以每轮执行一次，而不是每个提交执行。
- **处置**：待处理。

### REVIEW45-008 `NO_CURRENT_BAR` 未纳入原因词表

- **定位**：设计 DS45-04 第 3 条使用 `NO_CURRENT_BAR`；DS45-08 的指标不可用原因列表未包含它。
- **严重程度**：实施前需澄清（中低）。
- **问题与影响**：DS45-08 的 reason 是机器可读、验收精确断言的；`NO_CURRENT_BAR` 是 availability 层的原因，不是绩效指标层的原因。当前两份列表没有区分“可用性原因”和“指标原因”，实现者可能使用不同字符串或在错误层记录，导致 AC45-03 的断言不稳定。
- **建议**：明确两层 reason 词表：availability 层至少包含 `NO_CURRENT_BAR`、`MISSING_INPUT` 等；绩效层保持现有 `INSUFFICIENT_ASSETS` 等。把 `NO_CURRENT_BAR` 写入 DS45-03/04 的 availability schema 与 AC45-03 的断言。
- **处置**：待处理。

### REVIEW45-009 单目标/单资产运行的语义未明确

- **定位**：需求 §3“单资产数据不构成已通过的截面研究”、§4.2 排除“单资产时序 IC”；DS45-02 的 `min_assets >= 2`；AC45-14。
- **严重程度**：实施前需澄清（中）。
- **问题与影响**：`targets=("A",)` 在配置层面是否合法没有定义。若允许，评价必然因 `min_assets >= 2` 而不可评价；若拒绝，应在何时抛什么错误（`ConfigError(INVALID_CONFIG)` 还是结果 `UNEVALUABLE`）没有规定。用户可能误以为单目标会得到“单资产 IC”，而本轮明确不支持单资产时序 IC。
- **建议**：明确选择一种：
  - 配置期拒绝 `len(targets) < 2`，抛 `ConfigError(INVALID_CONFIG)`；或
  - 允许采集，但评价固定返回 `UNEVALUABLE / INSUFFICIENT_ASSETS` 并在文档中强调不构成截面研究。
  无论哪种，都增加一个负例；微小型 fixture 仍可通过显式 `min_assets=2` 工作。
- **处置**：待处理。

### REVIEW45-010 FactorSpec/EvaluationSpec 与示例中的 dict/kwargs 形态未冻结

- **定位**：设计 DS45-02 的 FactorSpec/EvaluationSpec；DS45-02 示例使用 `factors={...}` 字典和 `strategy.evaluate(preprocess=..., ...)` 关键字参数。
- **严重程度**：实施前需澄清（中）。
- **问题与影响**：文档一方面提出 `FactorSpec`/`ResearchSpec`/`EvaluationSpec` 数据类，另一方面示例只展示普通字典和关键字参数；没有说明：
  - `factors` 的值必须是 `FactorSpec`，还是也接受可规范化的 dict；
  - `strategy.evaluate(**kwargs)` 是否等价于构造 EvaluationSpec，是否两者都支持；
  - 传入未知字段、混用两种形态时的错误类型。
  这会让 R1 的“公开签名冻结”出现多个合理实现，验收却无法判定。
- **建议**：在 R1 明确：以 `FactorSpec`/`EvaluationSpec` 为权威类型；允许 `factors` 的 mapping sugar（规范化为 FactorSpec）和 `evaluate` 的关键字便利入口（构造 EvaluationSpec），并写一个最小测试覆盖两种调用产生同一评价身份；未知字段一律 `ConfigError(INVALID_CONFIG)`。
- **处置**：待处理。

### REVIEW45-011 `max_loss` 超限直接中止与 PARTIAL 状态的关系需要明确

- **定位**：设计 DS45-08；验收 AC45-14。
- **严重程度**：实施前需澄清（中）。
- **问题与影响**：DS45-08 说“超过任一请求序列的上限返回 `DataQualityError`”，这意味着三个因子中只要一个损失 40%，整个评价就中止，即使另外两个因子有合法结果也不能得到 PARTIAL 报告。PARTIAL 目前只覆盖“损失未超限但某些指标退化”的情形。这个业务假设是合理的（研究完整性优先），但文档没有明确说明用户会失去“其他有效因子”的可见性。
- **建议**：保留 v1 的严格 fail-closed 行为（推荐），但在 DS45-08/AC45-14 明确写出“任一请求 slice 超限即整体 `DataQualityError`，不返回 PARTIAL”；增加一个“一个信号超限、另一个有效”的测试，断言整体抛错而不是静默部分成功。若未来需要部分报告，再引入显式的 `loss_policy`，不要在本轮隐式放宽。
- **处置**：待处理。

### REVIEW45-012 因子定义指纹、`price_basis` 与 `snapshot_id` 的语义未定义

- **定位**：设计 DS45-03 provenance；DS45-09 manifest；DS45-02 ResearchSpec。
- **严重程度**：实施前需澄清（中低）。
- **问题与影响**：方案要求记录“因子定义指纹”并区分“改公式需重新采集”，但没有定义指纹由哪些字段组成（模块+qualname、参数、输出线、输入绑定、方向、指标源码哈希？）；`price_basis` 和 `snapshot_id` 目前是自由字符串，没有唯一性/取值约束。结果是：
  - 两个不同公式可能得到相同指纹，追溯失效；
  - 同一 `snapshot_id` 可能对应不同数据快照；
  - 改动方向是否算“公式变更”也没有说明。
- **建议**：定义指纹 recipe 并写入 DS45-03/09；明确 `price_basis` 的最小词汇或必填 provenance 字段；规定 `snapshot_id` 的唯一性/来源；在 manifest schema 和 AC45-15/22 中加入对应断言。方向覆盖应记录为评价身份的一部分，而不是原始指纹的一部分（与 REVIEW45-003 协同）。
- **处置**：待处理。

---

## 5. 可选建议

### REVIEW45-013 为两个示例定义最小 `config.yaml` schema

- **定位**：DS45-10；examples 四件套。
- **建议**：在 DS45-10 或示例 README 中给出 `config.yaml` 的字段表（研究 grid 来源、targets、source_timezone、snapshot_id、price_basis、因子类/参数/输出线/方向、数据路径、评价默认值、segments），并让 `run.py` 在启动时校验。否则 R6/R7 可能出现两份结构不同、无法互相复制的示例配置。
- **严重程度**：可选建议。

### REVIEW45-014 在 R1 内设置“合同与 fixture 冻结”检查点

- **定位**：迭代计划 R1。
- **建议**：R1 同时包含公开合同冻结、FactorStrategy、绑定、采集、runonce/runnext 和多个 AC，是风险最大的一轮。建议在 R1 内部设一个无代码的检查点：先冻结 FactorSpec/ResearchSpec/EvaluationSpec 字段、错误码、grid/timezone 合同和 fixture，再开始实现；不必新增轮次，但要在轮次记录中留下该检查点。
- **严重程度**：可选建议。

### REVIEW45-015 `groups` 默认全 `default` 对跨市场 target 的误导风险

- **定位**：DS45-02 `groups` 默认；DS45-03 组语义。
- **建议**：若 `targets` 跨越不同日历/收盘时刻/市场，要求显式提供 `groups` 或在采集开始时给出明确警告；默认全 `default` 可能让用户把不可比资产放进同一截面排名。至少应在示例和用户指南中强调“同组才可比”，并在结果 manifest 中记录组声明。
- **严重程度**：可选建议。

### REVIEW45-016 `universe` 的额外行/组覆盖边界

- **定位**：DS45-02/03 的 universe/groups 校验。
- **建议**：明确 `universe` 中不属于 research grid×targets 的额外行、`groups` 缺失某些 target、warmup/tail 行是否需要覆盖时的处理（拒绝还是忽略并计数），并加一个负例。此项可与 REVIEW45-002 的 grid 构造器一起实现。
- **严重程度**：可选建议。

---

## 6. 对 README §3 八个外审问题的回答

| # | 问题 | 结论 | 说明 |
|---|---|---|---|
| 1 | 使用成本是否足够低、信息是否可获得 | **部分满足** | Indicator 复用方向正确；但 `grid/calendar/source_timezone` 仍需用户手工构造，且示例中的 `closed_bar_grid` 未定义。补 REVIEW45-002 的构造器/字段后，成本才与“只写 Indicator/配置”的目标匹配。 |
| 2 | 多资产/多输入的保守边界是否合理 | **合理** | 单次 run 一个 grid、目标+一个基准、完整对齐，能避免陈旧值和模糊缺失；需要补 tick/resample 负例。 |
| 3 | 标签与样本规则是否泄漏/压缩 | **合理** | h 按研究 bar、next-open 需 h+1 尾部、缺价不跳行、先分位后标签；fixture 正确。分段边界和尾部损失需要在 AC 中显式断言。 |
| 4 | 多因子比较/消融是否有样本偏差 | **基本合理** | 共同池、池内重算、消融不扩池、配对 delta 均正确；需要澄清 max_loss 超限与 PARTIAL 的交互（REVIEW45-011）。 |
| 5 | 退化与统计默认是否适合业务 | **基本合理** | qcut 不拆 ties、分位失败保留 IC、ICIR 不年化、ddof/分母明确；实现时必须避开旧 `prepare_factor_data_by_horizon` 的丢行/损失口径（REVIEW45-005）。 |
| 6 | 跨仓接口是否重复/隐式/循环依赖 | **清晰，但缺能力标识** | 分工清楚、fincore 先行、BT 不重写统计；需增加 fincore API 能力版本/运行时检查（REVIEW45-006）。 |
| 7 | 可验收性是否足够区分正确/错误实现 | **较强，但需补缺口** | 手算 fixture 质量高；缺 PARTIAL、tick/resample、方向覆盖、JSON 非有限值、覆盖写、重复键冲突（REVIEW45-004）。 |
| 8 | 范围与节奏是否合理 | **合理** | 排除 ML/HAC/实盘等是恰当的；R1 偏大，建议内部检查点；其余轮次顺序正确。 |

---

## 7. 追溯与验收覆盖缺口汇总

| 缺口 | 需求/设计 | 现有 AC | 处理建议 |
|---|---|---|---|
| 方向离线覆盖 | REQ45-04 / DS45-02 | AC45-15 未覆盖 | 增加 `direction_overrides` 字段与复评断言 |
| tick / resample 不支持 | REQ45-03 / DS45-04 | AC45-05 只列部分时钟 | 增加 `UNSUPPORTED_CLOCK` 负例 |
| PARTIAL 状态 | REQ45-09 / DS45-08 | AC45-14 无显式正例 | 增加 F-PARTIAL |
| JSON null / CSV 空字段 | DS45-08 | AC45-17 未断言 | 增加非有限值/空字段断言 |
| 覆盖写拒绝 | DS45-09 | AC45-15/17 未覆盖 | 增加已存在目录负例 |
| 同一键不同值冲突 | DS45-04 | AC45-03 只覆盖重复采样 | 增加 F-DUP-KEY |
| `NO_CURRENT_BAR` 词表 | DS45-04 | AC45-03 未断言 | 明确 availability reason 层 |
| 因子定义指纹 | DS45-03/09 | AC45-15/22 未定义 | 定义 recipe 并断言 |
| fincore 能力检查 | DS45-09 | AC45-13/22 只记录来源 | 增加 API 能力版本与运行时检查 |

---

## 8. 建议的修订顺序

1. **确认基线前（必须）**：REVIEW45-001、002、003、004。它们是事实性/合同性矛盾或验收缺口，修订成本低，但不修订会让后续实现和验收建立在错误前提上。
2. **R1 合同冻结前（强烈建议）**：REVIEW45-005、006、007、008、009、010、011。把 fincore 复用边界、能力检查、时钟回归、reason 词表、单目标语义、API 形态和 max_loss 行为写入 R1 合同与 fixture。
3. **R1 开始前（可选）**：REVIEW45-012、013、014、015、016。它们不阻断实现，但能减少 R1/R6/R7 返工。
4. 修订后重新执行：五份文档的链接/BOM/编号检查；REQ→DS→AC 追溯检查；统计 fixture 手算复核；确认 AC45-01..22 仍全部 NOT_RUN 且未被误标 PASS。
5. 只有完成第 1 步后，才建议把文档标记为“已确认基线”并开始 R1；第 2 步可在 R1 的合同冻结检查点完成。

---

## 9. 证据、复现与限制

### 9.1 主要源码证据

- `backtrader/setup.py:53-71`：pandas/matplotlib 为必需依赖；`:109` Python >=3.8。
- `backtrader/utils/dateintern.py:373`：`num2date(x, tz=None, naive=True)`。
- `backtrader/indicators/momentum.py:156` 起：ROC 分母为 0 返回 0.0。
- `backtrader/indicators/stochastic.py:214`、`backtrader/indicators/contrib/shared_strategy_indicators.py:1243-1299`：StochasticFull/KDJ。
- `backtrader/_cerebro/runonce.py:101-116`：现代 runonce 取所有 feed 的最小下一时点。
- `fincore/fincore/factor_analysis/performance.py:72-97`：固定 Spearman IC；`:290` 换手；`:356` 分层收益默认 demean。
- `fincore/fincore/factor_analysis/data.py:321-335`：`_loss_report.total_loss` 含 binning loss；`:441` 起 `prepare_factor_data_by_horizon`；`:526` 分位缺失删行。
- `fincore/fincore/factor_analysis/analysis.py:395,741`、`models.py:1474`：`include_portfolio_inputs=True`。
- `fincore/pyproject.toml:7,15`：版本 `0.5.1.dev0`、Python >=3.11。
- `examples/README.md:14-15`：四件套标准。

### 9.2 只读运行时探针

- `import backtrader`：Python 3.14.2，`pandas_loaded=True`，`matplotlib_loaded=False`，`fincore_loaded=False`。
- KDJ：`_minperiod=13`；零振幅输入得到 `K=D=J=NaN`。
- ROC/SMA：`ROC(period=20)._minperiod=21`，`SMA(period=20)._minperiod=20`。
- fincore：`__version__=0.5.1.dev0`，HEAD `2354bb56…`，工作区干净。

### 9.3 限制

- 本次没有运行任何账户、网络、真实 provider、认证或功能验收；所有运行时探针均为本地只读、合成数据。
- 本次没有验证 fincore 新接口（尚不存在），也没有验证示例的可复制/安装产物（尚未实现）。
- 本报告不评价因子盈利性、IC 正负或市场有效性；这些也不是方案的正确性条件。
- 关于“使用的大模型名字”：按 Qoder 运行约束不披露底层模型标识；报告署名使用 Qoder Agent。若需要横向对比，请以产品名归档本报告。

---

## 10. 声明

本报告只审阅文档与现有源码，不接受任何既有实盘、历史认证或其他迭代的能力；不修改迭代 45 方案、不修改 fincore 工作区、不创建功能代码、不提交 Git。报告中所有“已验证”结论仅指本次只读核查范围；所有 AC45-01..22 仍为 NOT_RUN，功能验收尚未开始。

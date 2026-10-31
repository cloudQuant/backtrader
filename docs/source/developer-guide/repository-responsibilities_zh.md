# 仓库目录与文件职责规范

> 状态：现行开发约定；盘点基准：2026-10-31 的 `dev` 工作区，包含尚未提交的迭代 53 迁移。本文不是逐文件代码审计报告，也不证明未验收代码可用。首次使用和每次准备修改本仓库前，先读本文，并以实际代码、构建配置及适用的 `AGENTS.md` 为准。

## 1. 如何使用和维护

新增或移动文件前，先确认其运行者、生命周期、依赖方向和是否随发行包交付，再按下文最具体的规则选择位置。修改已有文件前，先检查现有调用者、公开 API、打包、文档和测试；位置不合适不等于可以直接移动。新职责没有合适位置时先说明方案，避免随意增加顶层目录。目录职责变化时同步更新本文和 `AGENTS.md`；行为变化同步更新用户文档和测试。本文不覆盖用户的具体指令，不授予账户操作、数据删除或迁移授权。

判断次序：具体文件和子目录规则优先于上级目录规则；测试夹具、历史证据和生成物按实际用途而非扩展名分类。不能确定归属的文件应标为“待核查”，检查生产导入、调用者、打包和维护者后再定，不应凭名字推断。这里定义所有文件的**归属规则**，并单列关键文件；历史文件不因此自动认定为合规或已逐个核查。

### 共同边界

- `backtrader/` 是发行包：放框架运行所需的接口、实现及明确需要的包数据。生产路径不依赖 `tests/`、`examples/`、`scripts/` 或 `docs/`。`__init__.py` 负责有意公开的导出与必要的包初始化，不承载任务执行或不必要的外部副作用；公开符号变更须考虑兼容性。
- `tests/` 证明合同，`examples/` 展示调用，`scripts/` 提供仓库维护入口，`docs/` 解释和记录；这些目录不能成为框架运行时的隐式依赖。复杂可复用的生产逻辑应归入适当的包模块，脚本和示例负责参数、装配与入口。
- 实验、性能结果和历史证据与受支持产品区分，标注条件、版本、证据等级与入口；模拟测试不能冒充真实账户验收。已冻结证据、受保护输入和已消费调用不得随整理改写或重跑。
- 回测、数据、订单、账户和时钟合同需明确；不支持的能力显式拒绝，不能静默降级或伪造成交。模式名本身不授予写权限。SDK 与服务进程由各自项目负责，框架接入以明确接口、边界和生命周期为准。
- 依赖按职责与实际合同设计，并以测试验证；不要将目录名字直接当成已实施的严格分层，尤其是历史模块。私有模块下划线不是公开 API；兼容入口、可选依赖及包导入副作用需单独核查。

## 2. 仓库根目录

| 路径或文件类型 | 应承担的职责和放置规则 |
| --- | --- |
| `README.md` | 用户入口、安装与快速开始、功能边界及主要文档链接；详细设计放 `docs/`。 |
| `AGENTS.md` / `CLAUDE.md` | 面向相应工具的开发指引；本规范是职责规则入口。现有目录摘要应随结构变化同步核对，避免继续复制并产生分叉。 |
| `CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md`、`LICENSE` | 分别记录贡献方式、安全报告、变更历史和许可；各自维护，不混放运行逻辑。 |
| `pyproject.toml`、`setup.py`、`requirements*.txt`、`Makefile` | 构建元数据、安装依赖和开发任务入口；确认实际生效配置，避免多处冲突。 |
| `pytest.ini`、`conftest.py` | 测试发现、标记、跨测试共享配置；特定测试支持优先放就近的 `conftest.py` 或 `tests/`。 |
| `.github/`、质量工具配置、`.gitattributes`、`.gitignore` | CI、格式检查、版本控制与平台规则；精确保护冻结字节及私密输入。 |
| `backtrader/`、`tests/`、`examples/`、`docs/` | 分别为产品代码、验证、用例和文档，详见下文。 |
| `scripts/`、`tools/`、`test_support/` | 仓库任务、辅助工具、跨测试支持；新增前先寻找现有入口，不因名称不同重复实现。 |
| `archive/` | 明确退役的历史材料；默认不参与运行、测试或分发，不作为兼容回退。 |
| `studies/`、`promotion/`、`assets/` | 研究材料、推广材料和项目资源；区分源文件、第三方许可和生成物，不当作运行时依赖。 |
| `reports/`、`artifacts/`、`_bmad-output/` | 报告、交付物和工作流产物；逐项辨别有意跟踪的历史材料与本地产物，新增时注明生成方式及是否需版本化。 |
| `.codex-tmp/`、缓存、虚拟环境、`build/`、日志等 | 本地工作或生成目录；不放唯一权威源码，不默认提交。已跟踪的例外按其明确用途和冻结要求处理。 |
| `.env.example`、示例配置 | 不含凭据的模板。真实 `.env`、账户配置和私密捕获不属于源码审查材料，遵守 `AGENTS.md` 的受保护读取规则。 |

根目录新增文件应是项目级入口或配置；临时补丁、一次性测试输出和个人环境文件应另行分类，不因当前存在就获得长期职责。

## 3. `backtrader/` 产品包

本项目保留现有平铺包布局。以下是职责边界，不要求为迎合模板立即重排公开模块。

| 目录或文件 | 职责 |
| --- | --- |
| `__init__.py`、`version.py`、`errors.py` | 明确的包入口与导出、版本、共享异常合同；避免入口强制加载不需要的可选依赖。 |
| `cerebro.py`、`_cerebro/` | `Cerebro` 公共装配入口与引擎执行、生命周期、通知、注册和运行循环的内部实现；保持普通引擎生命周期为唯一调度权威。 |
| `metabase.py`、`parameters.py` | 对象构造、参数与 owner 机制；保留当前显式构造合同。 |
| `lineroot.py`、`linebuffer.py`、`lineseries.py`、`lineiterator.py`、`dataseries.py` | 线数据接口、存储、组合、迭代及时钟依赖；改动要覆盖多数据、最小周期和两种引擎运行方式。 |
| `feed.py`、`resamplerfilter.py`、`feeds/`、`filters/` | 数据源抽象、具体 Feed、数据过滤和时间聚合；提供数据与时间语义，不负责策略或真实下单决策。 |
| `broker.py`、`brokers/`、`order.py`、`position.py`、`trade.py`、`comminfo.py`、`commissions/`、`fillers.py`、`position_modes.py` | Broker 合同与实现、订单/持仓/交易、费用及成交规则；实际服务能力和授权不应由名称或模拟结果推断。 |
| `store.py`、`stores/` | Store 抽象、公共 facade 和 Store 生命周期；现有具体实现仍含连接和装配，迭代 53 计划将其按职责拆分，迁移尚未完成。见第 6 节。 |
| `strategy.py`、`indicator.py`、`observer.py`、`analyzer.py`、`sizer.py`、`signal.py` | 策略和相应组件的公共基类、接口和生命周期。 |
| `indicators/`、`observers/`、`analyzers/`、`sizers/`、`signals/` | 各自类型的可复用实现；信号、分析与观察不应暗中更改账户。 |
| `research/` | 因子研究、面板与研究协议；计算仍服从引擎生命周期，下游分析通过既定外部接口接入，不复制其他项目的权威算法。 |
| `plot/`、`bokeh/`、包内 `reports/` | 绘图后端和报告展示；可选展示依赖不应无故成为核心导入前提。 |
| `channels/`、`channel.py`、`notifications/`、`events.py`、`timer.py` | 按现有公开合同处理通道、事件、通知与定时，不自行引入第二套引擎。 |
| `live_trading/`、`configs/`、`profiles.py` | 现有实盘配置及辅助能力、无凭据配置模板和配置投影；逐项确认支持状态，不存真实凭据。 |
| `btrun/` | 包内受支持命令/运行装配入口；命令只协调受支持能力，不把业务实现锁进 CLI。 |
| `mixins/`、`utils/`、`functions.py`、`mathsupport.py`、`flt.py`、`talib.py`、`tradingcal.py`、`writer.py` | 共享机制、数学/日期/外部库适配、交易日历和输出；优先放领域模块，仅在确有跨领域复用时放通用工具。 |
| `test_helpers.py` | 现有包内测试辅助兼容入口；新测试辅助优先放 `tests/`，移动此文件前先审查现有使用者和发行兼容。 |
| `adapters/`、`execution/`、`factor_execution/`、`service/` | 迭代 53 工作区中的候选位置：分别承载 BT 侧具体适配、BT 执行适配合同、BT 因子执行事实、BT 生命周期与服务桥接。CTP 原生协议、SDK 的 journal/dispatch 和持久执行真值仍由对应 SDK 项目负责。当前未提交，须以该轮方案与验收为准，不能视为已发布或已完成迁移。 |

每个子目录里的 `.py` 文件应围绕该目录的一项连贯职责；`__init__.py` 是包入口，具体实现按业务命名。包内数据仅保留运行必需且明确加入分发的无秘密资源；测试样本与大型结果放测试或证据位置。不要以“utils”“common”为理由聚合不相干的职责。

## 4. 测试、示例和工具

| 路径 | 职责 |
| --- | --- |
| `tests/unit/` | 对单个模块或合同进行隔离测试。 |
| `tests/integration/` | 组件边界和组装行为；真实外部依赖、账户和模拟替身必须明确区分。 |
| `tests/functional/` | 用户可观察的端到端/策略行为和回归；`strategies/` 是策略回归测试。 |
| `tests/performance/`、`tests/bench/` | 性能合同和基准；记录环境、统计口径，时间敏感测试按项目现有串行策略运行。 |
| `tests/fixtures/`、`tests/datas/`、`tests/assets/` | 稳定、无秘密的测试输入与资源；标注来源、许可、生成方法及是否冻结。 |
| `tests/factories/`、`tests/test_utils/`、`test_support/` | 测试对象工厂、测试工具和共享支持；不能作为产品实现的依赖。 |
| 其他 `tests/` 文件及子目录 | 依其实际测试目标、夹具或支持用途归类；历史布局不自动表明单元或集成证据等级。 |
| `examples/` | 用户可运行的配置、策略和示例说明；每项注明依赖、模式、外部服务与副作用。共享示例辅助只服务示例，不能成为包运行依赖。 |
| `scripts/`、`scripts/ci/`、`scripts/debug/` | 可发现的开发、CI、调试和一次性任务入口；应说明前置条件、输出和副作用。历史认证脚本要保留其证据语境，不应默认作为当前运行入口。 |
| `tools/` | 仓库辅助工具和专项验证；与 `scripts/` 的既有职责有交叉时，沿用相关工具的现有位置，不新造同义入口。 |

测试文件按被验证行为命名，夹具不得伪造未建立的生产事实；隔离测试、源码模拟、真实账户、安装包与性能证据分别报告。工具输出默认不回写源码目录或覆盖历史证据。

## 5. 文档与文件类型

`docs/source/` 放面向读者的文档：`getting-started/` 和 `tutorials/` 用于学习，`user-guide/`、`advanced/` 和 `migration/` 用于完成任务，`api/`、`reference/` 用于准确参考，`developer-guide/` 用于开发规范，`strategies-series/` 为策略系列。`locales/` 和 `_static/` 分别服务翻译与静态资源。实际站点入口和构建规则以文档配置为准；增加用户文档时同时检查导航和双语维护需求。

`docs/_internal/` 存内部计划、设计、迭代记录和明确保留的证据，不应成为唯一的用户使用说明。其他 `docs/` 路径以现有站点、内部项目和维护用途分类；生成文件不要冒充源文档。中文 Markdown 默认 UTF-8 BOM，既有格式及冻结证据例外见 `AGENTS.md`。

无论位于何处：源码实现合同；配置声明可验证参数和安全默认值；无秘密模板提供示例；测试断言行为；夹具是输入；文档解释用途；生成文件有可追溯来源；证据记录真实范围和时间。文件后缀不能决定是否公开、可执行、安全或可删除。

## 6. 已观察到的偏差与待核查事项

本节是带证据的工作区快照，不是全仓逐文件合规结论。优先级是处理建议，不授权重构或删除；每项修复都须核实调用者、兼容性和测试后独立验收。

| 优先级 | 事实与影响 | 建议后续动作 |
| --- | --- | --- |
| 高 | 迭代 53 的工作区删除了多项 `backtrader/stores/service_*.py`、执行及 CTP 文件，同时出现未跟踪的 `backtrader/service/`、`execution/`、`adapters/`、`factor_execution/`；当前 `AGENTS.md` 和 `docs/TRADING_SYSTEM_ARCHITECTURE.md` 仍有旧 `stores` 路径。CTP 合同的 BT 桥接与 SDK 协议边界尚须按迁移方案逐项核实。这是进行中的迁移，不能凭此判断最终 API。 | 按该轮重构完成调用点、测试、打包及文档迁移；完成并验收后更新旧指引。本文不修改该轮代码。 |
| 高 | 当前工作区 `backtrader/stores/btapistore.py` 仍从 `.managed_execution` 导入，而原路径已删除；新 `backtrader/adapters/ctp/registered_sim.py` 引用的 `adapters/ctp/stock_wrapper.py` 当前不存在。此处为静态检查，未运行导入，不代表最终迁移状态。 | 在迭代 53 内核实所有迁移调用点和缺失依赖，修复后分别验证基础导入与相关真实装配路径。 |
| 高 | `examples/unified/007_ctp/run_runtime.py`、`examples/unified/028_alpha003_simnow_minute/protected_simnow.py` 和 `scripts/ci/smoke_iteration41_registered_offline.py` 引用已退役的 `backtrader_runtime`；`pytest.ini` 排除 `archive`，不能依靠归档作为运行回退。 | 逐个核实是否仍为受支持入口；迁移或明确标注不可用及替代方式。不要恢复隐式兼容包。 |
| 中 | `backtrader/feeds/btapifeed.py` 从 Store 导入 `_build_ctp_tick_datetime`、`_normalize_bar` 私有函数；`backtrader/cerebro.py` 的 live cohort 路径直接依赖研究类型、精确 `BtApiFeed` 类型及其接口。这些事实表明边界有具体耦合，并不单独证明运行错误。 | 结合现有时钟与数据合同审查是否需要抽出窄接口；保留现有语义，避免为消除引用而破坏多数据行为。 |
| 中 | `backtrader/test_helpers.py` 位于发行包，其文档示例面向测试；`setup.py` 使用 `find_packages` 分发 `backtrader`。这使测试支持与产品包边界交叠，但不证明没有外部使用者。 | 查找调用者及兼容承诺；新测试支持放 `tests/`，旧文件是否迁移须单独评估。 |
| 中 | 历史认证脚本仍位于 `scripts/`，例如 `scripts/run_simnow_c01_native_td_read_v20_root_activation_r2.py` 指向退役包内路径；脚本存在不等于入口可运行或获准执行。 | 建立入口状态和历史证据索引，区分活跃工具与冻结记录；保留原始字节和已消费结果。 |
| 中 | `README.md`、`AGENTS.md` 和代码/构建配置存在可能过期或互相矛盾的信息，例如前者声明 PyPI 安装，而后者当前称仅能从源码安装；`setup.py` 的分发名称为 `back-trader-python`。 | 单独核实实际发布状态后统一说明；本规范不据此推断当前 PyPI 发行状态。 |
| 高 | `setup.py` 的许可证分类器写为 MIT，而仓库 `LICENSE` 是 GPLv3 文本，README 也标示 GPLv3；发行元数据与仓库声明不一致。 | 独立核实项目许可及发行元数据后修正；这里仅记录不一致，不作法律结论。 |
| 待核查 | `reports/`、`artifacts/` 等同时有已跟踪材料和可能的本地产物，`scripts/` 与 `tools/` 也有历史职责交叉。 | 先做逐项来源、依赖、冻结和保留策略盘点，再制定整理计划；不要批量删除或移动。 |

## 7. 提交前检查

1. 说明新增/修改文件属于哪个最具体的职责，公开接口、依赖方向和可选依赖是否改变；未分类项目先调查。
2. 检查真实调用者、导入、副作用、包数据和安装包；新入口有无重复、权限边界及可用性说明。
3. 测试与变更风险相称，按实际说明源码、模拟、安装包或真实账户的证据等级；文档链接、导航、编码及中英文同步按需核验。
4. 遵循现有 `dev` 小轮验收、精确暂存和提交，保留无关改动及冻结材料；结构改变时更新本文与 `AGENTS.md`。

## 8. 参考依据与适用范围

- [Python Packaging User Guide：src 与 flat 布局](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)：两种布局各有取舍；当前 flat 布局需特别验证安装包与源码导入来源，并不因此要求迁移到 `src/`。
- [pytest：Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)：测试布局和导入方式影响验证对象，应有意识区分安装包与源码测试。
- [Python 导入系统：Packages](https://docs.python.org/3/reference/import.html#packages)：包提供模块命名层次；文件夹本身不自动保证职责或依赖方向。
- [Diátaxis 文档框架](https://diataxis.fr/)：教程、操作指南、参考和解释对应不同读者需求；不要求机械创建四套目录。

这些参考提供通用原则；本仓库的具体边界、兼容例外和迁移顺序是结合当前代码与工作流程制定的项目约定，并非某个外部标准规定的唯一目录树。

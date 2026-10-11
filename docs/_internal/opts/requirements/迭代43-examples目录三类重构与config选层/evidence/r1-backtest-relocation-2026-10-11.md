# R1 — `examples/backtest/` 搬迁与自包含守卫叶子化（2026-10-11）

比较基准：`evidence/r0-baseline-freeze-2026-10-11.md` §3。主仓提交基线 `75080cbea`。

## 1. 本轮改动

### 1.1 目录搬迁（11 个 A 类目录）

`001_multi_extend_data`、`002_hft_alignment_demo`、`003_hft_notebook_examples`、`004_midfreq_demo`、
`005_midfreq_arbitrage`、`006_plots`、`008_dual_side`、`009_trade_logger`、`011_hft_backtest`、
`016_self_similarity`、`017_fnn_embedding` → `examples/backtest/<同名>`（全部 `git mv`）。

跟踪面：**74 条 rename**，其中 **60 条 `R100`**（内容逐字不变）、**14 条含必要路径适配**；另有 6 个非示例文件被修改
（`docs/PLOTTING_BACKENDS.md` + 5 个测试文件）。`git diff --cached -M` 复核：非 `R100` 集合恰为下表 14 个文件与这 6 个文件，
无其它隐性内容改动。

### 1.2 仓库根定位必要适配（14 文件）

| 文件 | 改动 |
|---|---|
| `backtest/001_multi_extend_data/run.py:36` | `BASE_DIR.parent.parent` → `...parent.parent.parent` |
| `backtest/005_midfreq_arbitrage/run.py:10` | `sys.path.insert(..., "..", "..")` → 三级 `..` |
| `backtest/006_plots/example_bokeh_charts.py:23`、`example_plotly_charts.py:23`、`example_report_generation.py:25` | 三层 `os.path.dirname` → 四层 |
| `backtest/008_dual_side/dual_side_{basic,hedge,vs_net}.py` | `("..", "..")` → 三级 `..` |
| `backtest/009_trade_logger/trade_logger_example.py:25` | `("..", "..")` → 三级 `..` |
| `backtest/009_trade_logger/trade_logger_heikin_ashi_example.py:18` | `BASE_DIR.parents[1]` → `parents[2]` |
| `backtest/011_hft_backtest/{orderbook_backtest,tick_backtest}.py` | `parents[2]` → `parents[3]` |
| `backtest/016_self_similarity/run.py:45`、`backtest/017_fnn_embedding/run.py:52` | `HERE.parent.parent` → `...parent.parent.parent` |

`002`/`003` 只用 `EXAMPLE_ROOT = Path(__file__).resolve().parent`（数据 `data/` 随目录整体搬迁），无需适配，实测证实。

### 1.3 引用侧修正（活跃引用）

| 文件 | 改动 |
|---|---|
| `tests/functional/strategies/time_based/test_0201_self_similarity.py:23-26` | 模块名 `examples.backtest.016_self_similarity.run` + config 路径加 `backtest` |
| `tests/functional/strategies/time_based/test_0202_fnn_embedding.py:24-27` | 同上（017） |
| `tests/unit/test_self_similarity_example.py:21` | 策略模块 dotted 名（按 100 列宽折行） |
| `tests/unit/test_fnn_embedding_example.py:20,183` | 策略与 autoencoder dotted 名 |
| `docs/PLOTTING_BACKENDS.md:69-70` | 活跃用户文档路径 |

`CHANGELOG.md:253-254` 属历史条目，按四角色原则**保留旧路径不改写**。

### 1.4 自包含守卫叶子化（回应评审 P1 06）

`tests/unit/test_examples_self_contained.py`：

- 新增 `CATEGORY_DIRS = {"backtest","live","unified"}`；`_example_folders()` 改为**逐示例叶子**发现
  （`examples/<name>` 或 `examples/<category>/<name>`），类别目录本身永不作为示例参数。
- 抽出 `_is_example_leaf()` 供两条分支复用。
- 新负例 `test_category_directory_is_not_treated_as_one_example`：同类别两个叶子中，`first/entry.py` 导入
  `second_helper` 必须报违规，且发现结果必须是两个叶子而非一个类别目录。
  该负例首次实现时把期望写成了 `"first/entry.py …"`，实测违规消息带类别前缀（`backtest/first/entry.py …`），
  已改为由 `entry.relative_to(tmp_path).as_posix()` 构造，避免平台分隔符假设。
- `OPTIONAL_EXAMPLE_MODULES` / `COMPATIBILITY_STDLIB_MODULES` 仍按 `folder.name` 键，未因层级变化失效。

## 2. 验收结果（逐项 vs R0 基线）

| 门禁 | R0 基线 | R1 实测 | 判定 |
|---|---|---|---|
| `tests/unit/runtime -q` | 746 passed / 23 skipped / 0 failed | **746 passed / 23 skipped / 0 failed**（19.37s） | 无新增回归 |
| 守卫+示例聚焦集 | 81 passed / 3 failed（3 项白名单既有红） | **3 failed / 30 passed**（self-contained 单文件）；四文件聚焦 **82 passed / 3 failed** | 3 项既有红逐项不变，新增 1 项通过（负例） |
| `test_0201`/`test_0202` + `test_fnn_embedding_example` + `test_self_similarity_example` + `tests/functional/strategies/time_based` | — | **83 passed** | 新路径可导入、结论不变 |
| `ruff check examples` | 176 errors | **176 errors** | 未增加 |
| `ruff check backtrader` / `backtrader_runtime` | clean | clean | 硬门保持 |
| `find_packages(exclude=…)` | 不含 examples | `examples-ish collected: []` | 新父目录未被意外收包 |
| `git diff --cached --check` | — | clean | — |
| `make format-check` | 本机 black 为 `0.0` 占位、不可执行 | 未作为门（按 R0 §3 以 ruff 增量替代） | 环境缺口，非本轮回归 |
| `make test-strategies`（`tests/functional/strategies`，1,286 项） | 迭代 42 记录为绿；本机 R0 未预跑 | **1286 passed / 0 failed**（`-p xdist -n 8`，5:47） | 完整策略验收通过 |

## 3. A 类能力登记回填（实测）

| 条目 | 结果 | 说明 |
|---|---|---|
| `004_midfreq_demo/run.py` | exit 0 | |
| `005_midfreq_arbitrage/run.py` | exit 0 | 三级 `..` 修正后 `sys.path` 仍解析到仓库根 |
| `008_dual_side/dual_side_basic.py` | exit 0 | 其余两份同源，同一修正 |
| `009_trade_logger/trade_logger_example.py` | exit 0 | 输出 BT_SYSTEM JSON 行 |
| `011_hft_backtest/{tick,orderbook}_backtest.py` | exit 0 | |
| `006_plots/`（3 份） | exit 0（需 `PYTHONIOENCODING=utf-8`） | 默认 GBK 控制台在打印 `✓` 处 `UnicodeEncodeError`，属 Windows 控制台编码，非搬迁缺陷；已用 UTF-8 口径复跑全绿。`006_plots/output/` 由既有 `/examples/**/output/` 忽略规则覆盖，未产生脏跟踪文件 |
| `003_hft_notebook_examples/run_backtrader.py` | exit 1 `FileNotFoundError: Missing required precompute_data …` | **符合要求的离线拒绝**：无自动联网补齐（`prepare_data.py:29` 的下载能力未被触发） |
| `002_hft_alignment_demo/run_backtrader.py` | exit 1 `KeyError: 'orderbook'` | **既有缺陷，非本轮引入**：用 `git archive` 取出搬迁前的原目录副本在临时路径实跑，得到同一 `KeyError: 'orderbook'`；该目录内容本轮 `R100` 未改，且其路径解析只用 `EXAMPLE_ROOT` |
| `001_multi_extend_data/run.py` | exit 1 `TypeError: TradeLogger.__init__() got an unexpected keyword argument 'log_data'` | **既有缺陷**：`HEAD:examples/001_multi_extend_data/run.py:184` 即传 `log_data=True`，而 `backtrader/observers/trade_logger.py:187` 的参数集只有 `log_bars`，无 `log_data`（`git log -S log_data` 显示该串从来只作局部变量名）。本轮的根定位修正反而使其越过原先的 `FileNotFoundError: bond_index_000000.csv`，暴露出真实断点 |
| `016_self_similarity` / `017_fnn_embedding` | 由 `test_0201`/`test_0202` + 两份单测覆盖，83 passed | 未单独 CLI 跑 |

## 4. 遗留（已登记归属，不混入本轮）

1. **`001` 的 `log_data` → `log_bars` 参数名陈旧**（示例侧一行修正，属行为修复，另起小轮）。
2. **`002` 的 `KeyError: 'orderbook'`**（数据字段/hftbacktest 契约，需独立诊断轮）。
3. **`006` 依赖控制台 UTF-8**：可在 README 注明或改为 ASCII 输出（行为变更，独立小轮）。
4. **测试会写跟踪产物**：`tests/functional/strategies/time_based/test_0202_*` 运行 017 时向
   `examples/backtest/017_fnn_embedding/reports/train_report.jsonl` **追加内容**（聚焦跑 +71 行，
   全量策略回归后再 +6 行）。本轮每次都先用 `git show HEAD:…` 还原为 70 行、确认回到 `R100` 再提交；
   该"回归测试污染跟踪工件"问题需独立轮次处理（改写 `tmp_path` 或纳入忽略），
   否则任何策略回归都会持续污染该文件。
5. `make format-check` 在本机 black `0.0` 下不可执行，属环境能力缺口。
6. **`make test-strategies` 本机不可直用**：其 `-n 8` 会加载 `pytest_asyncio`，与 pytest 8.0 的 `Package`
   收集 API 不兼容，产生 8 个 `AttributeError: 'Package' object has no attribute 'obj'` 收集期 ERROR
   （与本轮改动无关，`-n 2` 同样复现）。本轮改用
   `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 … -p xdist -n 8` 口径，与迭代 41/42 记录的兼容 venv
   （pytest 8.2.2 / pytest-asyncio 0.24.0）不同，后续轮统一沿用本文口径。
7. **R4 需复查三处内联数据搜索**：`tests/functional/strategies/{order_types/test_05_stop_order_strategy, special/test_02_multi_extend_data, trend_following/test_03_two_ma}.py`
   各自内联 `repo_root / "examples" / filename` 搜索路径；当前 CSV 仍在 `examples/` 根故不受影响，
   R4 把数据移入 `examples/data/` 时必须同步（"数据移动与消费者路径修复同轮交付"）。

## 5. 完整策略回归结果

`tests/functional/strategies`：**1286 passed / 0 failed / 14 warnings，347.94s（5:47）**。
其中 4 个文件直接引用 `examples/` 路径（`time_based/test_0201|0202` 走新路径，另 3 个为内联数据搜索，见 §4 第 7 条）。

## 6. 提交卫生纠正（本轮自记）

首次提交用了宽 pathspec `git add -- examples tests docs <迭代43>`，在同一工作区存在并发会话的前提下扫入了两类非本轮内容：

1. 另一会话未跟踪的 `迭代1-穿透式认证/evidence/iteration41-zmq-combined-import-r5-…-2026-10-06/` 5 个文件；
2. 另一会话在编的 `tests/unit/runtime/test_ctp_simnow_config_operator_route.py`。

处置：`git reset --soft HEAD^` 撤销该提交（未推送、无历史丢失），逐项 `git restore --staged` 摘出上述 6 个路径，
确认它们在磁盘与对方索引状态原样保留，再按纯索引提交。最终提交面实核为
**60 条 `R100` + 13 条 `R099` + 1 条 `R098` + 6 个测试/文档修改 + 1 个本轮记录新增**，无其它内容改动。

顺带澄清一次误判：`001/config.yaml`、`001/strategy_multi_extend_data.py`、`017/optimize_results.{csv,json}` 一度被疑为
测试运行改写，改名感知（`-M`）复核均为 `R100` 纯改名；本轮真实的跟踪工件污染只有
`017/reports/train_report.jsonl`（§4 第 4 条），已两次还原后提交。

后续轮次约束：**本工作区一律按显式文件路径 `git add`，不使用目录级宽 pathspec**；提交前必查
`git -c core.quotePath=false diff --cached -M --name-status` 的 `A`/`M` 集合是否全属本轮。

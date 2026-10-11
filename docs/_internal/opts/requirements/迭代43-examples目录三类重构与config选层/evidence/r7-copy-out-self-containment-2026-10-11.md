# R7（进行中）— 每个示例目录"复制到别处也能跑"

用户 2026-10-11 追加要求：每个目录自包含，**在 `examples/` 内能跑，被复制到别的文件夹也要能跑**。
本轮据此实测后拆片推进；已定的两个策略：

- **小数据随目录走**（≤1MB 级：`2006-day-001.txt` 0.01、`113013.csv` 0.13、`nvda-1999-2014.txt` 0.26、
  `bond_index_000000.csv` 0.72MB）；**大数据保持外部 + `--data-dir`，缺数据明确 fail-closed**
  （`XAUUSD_M1.csv` 99MB 供 016/017、`tick_data/` 7.2MB 供 011、`DOGEUSDT_15m…csv` 23.5MB 供根级 bollinger）。
- **`backtrader_runtime` 走惰性导入**：本机 site-packages 只有 `backtrader`，`backtrader_runtime` 未安装，
  所以任何在模块加载期触到它的示例都必然"出了仓库就跑不动"。

## 1. 复制即可运行 —— 实测矩阵

方法：把叶子目录（剔除 `__pycache__/evidence/reports/logs/output/state`）复制进临时目录，`cwd` 设在副本内，
清掉 `PYTHONPATH`，跑其离线入口。

| 目录 | 复制后 | 根因 |
|---|---|---|
| `backtest/004` `backtest/005` | exit 0 ✅ | 本就自包含 |
| `backtest/011`（修前） | exit 0 ⚠️ **假通过** | 缺数据分支只 `print` + `return`，退出码仍是 0；docstring 却写明 `Raises: SystemExit` |
| `backtest/011`（修后） | exit 2 ✅ 诚实阻塞 | 已改 `raise SystemExit(2)`；仓库内两入口复跑仍 exit 0（`Ticks processed: 5000`、`P&L: -549.43`） |
| `backtest/001` | exit 1 ❌ | 需要 `examples/data/bond_index_000000.csv`（R4 后按仓库根解析） |
| `backtest/006`（3 脚本） | exit 1 ❌ | 需要 `tests/datas/nvda-1999-2014.txt` |
| `backtest/008`（3 脚本） | exit 1 ❌ | 需要 `tests/datas/2006-day-001.txt` |
| `backtest/009`（2 脚本） | exit 1 ❌ | 需要 `tests/datas/113013.csv`；`heikin` 版已用本地 `BASE_DIR/"datas"` |
| `backtest/016` `backtest/017` | exit 1 ❌ | config 里 `"{repo}/tests/datas/XAUUSD_M1.csv"` = 99MB，属大数据，按决策不随目录复制 |
| `unified/015`（dry） | exit 0 ✅ | — |
| `unified/014_2`（dry） | exit 1 ❌ | `ModuleNotFoundError: backtrader_runtime`；`run.py` 侧 `legacy_runner` **已是惰性导入**（`run.py:68-70` 函数内 `from . import legacy_runner`），所以触发点在其内部依赖链，需单独定位 |
| `live/000…/{binance,simnow}_penetration`（用例 dry） | exit 2 ⚠️ 设计如此 | 副本内 `status: DRY` 但 `env_keys_missing: [BINANCE_DEMO_API_KEY, BINANCE_DEMO_SECRET]`；在仓库内可跑是因为读到 checkout 根 `.env`。**代码可移植、凭据不外带**，不得为绕过它而放宽 |

## 2. 已完成切片

`backtest/011` 两入口的缺数据分支由 `return` 改为 `raise SystemExit(2)`（与各自 docstring 的 `Raises: SystemExit` 契约一致），
双路径复验见上表。这是"诚实性"修复：假成功的 exit 0 会让守卫测试误判为可运行。

## 3. 待做切片（顺序即建议顺序）

1. **R7-a 小数据入目录**：`001/006/008/009` 各建 `data/`，解析顺序改"先本目录、再仓库"，
   并把这批数据副本纳入 `test_examples_self_contained.py` 的**字节漂移守卫**（沿用 vendored-copy 模式，禁止静默发散）。
   复验口径 = 复制进临时目录后 exit 0。
2. **R7-b `backtrader_runtime` 惰性化**：定位 `014_2` dry 通道实际触达该包的调用链并下沉；
   复验 `012_1/012_2/014_1/014_2` 的 dry 在副本内 exit 0（其 replay/live 层仍合法地依赖仓库运行时，需写进各自 README）。
3. **R7-c 大数据 fail-closed 统一**：`011`（7.2MB）、`016/017`（99MB）、根级 bollinger（23.5MB）
   统一 `--data-dir` + 缺数据 `BLOCKED` 且点名缺失输入，禁止静默联网补齐（`003` 已是正确范式）。
4. **R7-d 守卫测试固化属性**：`tests/unit/test_iteration43_copy_out_runnable.py` 逐叶子复制到 `tmp_path` 跑离线入口，
   断言 exit 0，或（仅大数据/凭据类）断言"非零退出 + 消息点名缺失输入"；000 用例断言其阻塞原因必须是 `env_keys_missing`，
   防止把"缺凭据"降级成静默通过。

## 4. 门禁口径

沿用 R0/R2 冻结基线；R7 每片都要复跑：`tests/unit/test_examples_self_contained.py`、受影响示例的仓库内入口、
以及本文件的副本内复验矩阵；`ruff check examples` 保持 176 不增。

## 5. R7-a/b/d 已完成（2026-10-11 同日后续轮，覆盖 §1 表中相应行与 §3 待做序）

### R7-a 小数据入目录（`<leaf>/data/<file>`，先本地再仓库）

| 目录 | 随目录携带的副本 | 来源 | 解析改动 |
|---|---|---|---|
| `backtest/006_plots` | `nvda-1999-2014.txt` 277KB | `tests/datas/` | 3 个入口共 7 处 `os.path.join(PROJECT_ROOT,…)` → 目录内 `resolve_data_path()`（先 `data/`、再 `examples/data/`、再 `tests/datas/`，缺失即 `SystemExit` 并点名文件与候选路径） |
| `backtest/008_dual_side` | `2006-day-001.txt` 12KB | `tests/datas/` | 3 个入口各 1 处，同上 |
| `backtest/009_trade_logger` | `113013.csv` 137KB、`orcl-1995-2014.txt` 351KB | `tests/datas/` | `trade_logger_example.py` 2 处 → 同一 helper；heikin 版把 `BASE_DIR/"data"` 加为其搜索表首项 |

副本由 `test_examples_self_contained.py` 的 vendored 漂移守卫按发现登记（`examples/**/data/*` 命中
`tests/datas` 或 `examples/data` 原名者逐字节比对；002 的合成 `data/` 无仓库原名，不参与比对，不误伤）。

### R7-b `backtrader_runtime` 惰性化（本轮实测的真实阻断点）

触发点不是 `run.py`，而是各 `legacy_runner.py` 的**模块级** `from backtrader_runtime.legacy import (…)`。
改为 `_iteration41_legacy()` 按需导入，并把两处（config-first CLI、退役脚本的 fail-close raise）调用点改经该访问器：
`014_2` 手工完成，`012_1`/`012_2`/`014_1` 以锚定脚本同法完成（共 8 个调用点，别名残留断言全零）。
`012_2` 的 helper 初版插在 `import backtrader` **之前**，制造了 7 条 E402 新增红 —— 已把 helper 移到导入块之后，
`ruff check examples` 回到冻结值 176。此错误只在增量对比中可见，绝对计数不够。

### R7-d 复制即可运行的守卫固化：`tests/unit/test_iteration43_copy_out_runnable.py`

31 条用例逐目录用 `git ls-files -c -o --exclude-standard` 取"跟踪+新增、绝不含被忽略项"的副本，
清 `PYTHONPATH`、`cwd` 设在副本内跑离线入口，按**实测**分两类断言：

- 必须跑通（exit 0 且有输出）：`004 005 006×3 008×3 009×2`、`unified/012_2 013_1 013_2 013_3 014_1 014_2 015`；
- 必须 fail-closed 且**点名缺失输入**：`001`→`bond_`、`003`→`bookTicker`、`011×2`→`Generate test data`、
  `016/017`→`XAUUSD_M1.csv`、`012_1`→`checkout's backtrader package`（其 legacy_runner 有
  "必须使用本 checkout 的 backtrader 包"的受控栅栏，属设计约束，放宽它是独立治理决定，本轮不动）。

外加 24 条"副本内不得携带 `.env`/`secrets*`/`__pycache__`/`logs`/`state`"的私有输入守卫。
`002` 不入表：其 `KeyError: 'orderbook'` 是已登记的既有功能缺陷，与可移植性无关，
把它写成"通过"或用例失败都会掩盖真实缺口。
若该解释器离开 checkout 就导不到 `backtrader`，整套以 skip 带原因退出，不伪装成可移植性结论。

### 复验结果（对照 R0/R2 冻结基线）

`test_iteration43_copy_out_runnable.py` + `test_examples_self_contained.py`：**84 passed / 3 failed**
（3 项即 R0 命名的既有红）；`tests/unit/runtime` + 012_x demo contract：**875 passed / 23 skipped / 0 failed**；
登记离线冒烟 **8 / 0 / 2**；`ruff check examples` **176**（本轮改动文件单独全清）。

### §1 表中行的当前状态（以本节为准）

`006/008/009` 三行由 ❌ 转 ✅（副本内 exit 0）；`014_2` 由 ❌ 转 ✅；
`012_2`/`014_1` 由 ❌（`backtrader_runtime`）转 ✅；`012_1` 由 ❌ 转 ⚠️ 设计性 fail-closed（点名原因）；
`001/003/011/016/017` 维持 ⚠️ 大数据 fail-closed（已被守卫断言点名）；`011` 的假通过修复见 §2。

### 仍未做（R7-c 剩余与诚实边界）

- 大数据仍按 `--data-dir`/仓库解析，不随目录复制（`011` 7.2MB、`016/017` 99MB、根级 bollinger 23.5MB）；
  统一 CLI 参数化（而非仅靠 `BACKTRADER_DATA_DIR`）留待后续轮，现状已是"非零 + 点名"。
- `006` 三脚本依赖控制台 UTF-8（`✓` 字符）；守卫以 `PYTHONIOENCODING=utf-8` 运行，
  改为纯 ASCII 输出属已登记的独立行为小轮。
- `000` 认证套件副本内因缺 `.env` 而 `env_keys_missing`：代码可移植、凭据不外带，**不得为通过守卫而放宽**。

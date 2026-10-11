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

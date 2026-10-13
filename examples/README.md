# `examples/` 三类目录索引（迭代 43）

本目录只有三类示例，以及下面列出的支持目录与可重建产物目录。判定规则很简单：

| 类别 | 定义 | 目录 | 运行层 |
|---|---|---|---|
| **backtest** | 只做回测/离线分析，没有实盘通道 | `backtest/<id>/` | 离线 |
| **live** | 只做实盘穿透认证，没有回测通道 | `live/000_live_certification/<venue>_penetration/cases/<ID>/` | 干跑自检 + `--live` |
| **unified** | 回测与实盘一体，**由 `config.yaml` 的 `entry.tier` 选层** | `unified/<id>/` | `dry / replay / live` |

支持目录（不是示例，不得成为示例运行的依赖）：`_support/`（仓库级工具与权威材料、
`sample` fixture）、`data/`（多例共用只读 CSV）、`output/`、`logs/`、`__pycache__/`、`test_results/`（可重建产物）。

四件套标准：`README.md + config.yaml + <name>_strategy.py + run.py`，
`run.py` 退出码 `0/1/2/3 = PASS/FAIL/BLOCKED/UNKNOWN`，证据写各自 git-ignored 的 `evidence/`。

## 1. unified 能力登记表（迭代 43 实测，非计划）

| 目录 | 离线入口 | `entry.tier` 选层 | live 无写授权 | live 写通道 | 复制到别处 |
|---|---|---|---|---|---|
| `012_1_midfreq_cross_exchange` | `run.py --dry` / `--replay` | ✅ | `BLOCKED / live_observation_unavailable` | `--live --allow-write` + 目录内 hash 绑定清单 | ❌ 设计上绑定 checkout（须用本 checkout 的 `backtrader` 包） |
| `012_2_event_driven_cross_exchange` | 同上 | ✅ | `live_observation_unavailable` | 同上（`--mechanical-smoke` 为运营确认的有界机械层） | ✅ |
| `013_1_midfreq_cross_arbitrage` | 同上 | ✅ | ✅ `run_live_observe()` 零写会话 | `--live --allow-write` 写 drill | ✅ |
| `013_2_highfreq_calendar_arbitrage` | 同上 | ✅ | ✅ `run_live_observe()` | 同上 | ✅ |
| `013_3_sa_midfreq_simnow` | 同上 | ✅ | ✅ `run_live_observe()` | 同上 | ✅ |
| `014_1_ctp_options_lowfreq` | 同上 | ✅ | ✅ `run_live_observe()` | 同上（严格 feed 密封写 drill，另需 `--drill`） | ✅ |
| `014_2_ctp_options_midfreq` | 同上 | ✅ | ✅ live 层按契约只观察，`--allow-write` 首条语句即拒 | 无（本目录策略无下单路径） | ✅ |
| `015_ctp_options_highfreq` | 同上 | ✅ | ✅ 同上 | 无（`write_tier_not_implemented_for_decision_only_strategy`） | ✅ |
| `007_ctp` | 无 `run.py`：CTP 认证套件根 + 注册 runtime | n/a | n/a | 注册表零写 sandbox / 只读 preflight，`preflight` 仍 fail-closed | n/a |

选层真值表、`backtest` 别名、`entry_tier` 与既有 `tier`（结果层级标签）之别，见各目录 README 的
「运行层选择（迭代 43）」小节；判定器权威实现是 `examples/_support/entry_tier.py`，
每目录各带一份逐字节副本（漂移守卫 + 复制后可自行判层）。
**默认不在任何 `config.yaml` 写入 `entry.tier`**：缺省即保持迭代 42 的全部命令逐字可用；
声明后 CLI 只能保持或降低，不能上调，非法声明在任何 handler 之前 `BLOCKED`。

## 2. backtest 索引与数据边界

| 目录 | 离线入口 | 输入 | 复制到别处 |
|---|---|---|---|
| `001_multi_extend_data` | `run.py`（此例不解析 `--dry/--replay`） | `bond_merged_all_data.csv`(70MB) + `bond_index_000000.csv` | ⚠️ 非零退出并点名 `bond_*` |
| `002_hft_alignment_demo` | `run_backtrader.py` 等 | 目录内合成 `data/` | ✅ Backtrader 默认数据入口；hftbacktest 对齐未在本轮复验 |
| `003_hft_notebook_examples` | `prepare_data.py --skip-download` | 外部 `J:\binance-public-data…\bookTicker\BTCUSDT` | ⚠️ 非零退出并点名缺失文件 |
| `004_midfreq_demo` `005_midfreq_arbitrage` | `run.py` | 自带数据 | ✅ exit 0 |
| `006_plots` | `example_bokeh_charts.py` 等 4 个（`plot_plotly_example.py --output output/plotly_example.html` 无浏览器导出） | 目录内 `data/nvda-1999-2014.txt` | ✅（需 UTF-8 控制台，见 §4） |
| `008_dual_side` | `dual_side_*.py` 3 个 | 目录内 `data/2006-day-001.txt` | ✅ |
| `009_trade_logger` | `trade_logger_example.py`、`trade_logger_heikin_ashi_example.py` | 目录内 `data/113013.csv`、`data/orcl-1995-2014.txt` | ✅ |
| `011_hft_backtest` | `tick_backtest.py`、`orderbook_backtest.py` | `tests/datas/tick_data/`(7.2MB) | ⚠️ `exit 2` 指示先 `tools/generate_test_data.py`（假通过已修） |
| `016_self_similarity` `017_fnn_embedding` | `run.py`（`--config/--mode/--fromdate`） | `XAUUSD_M1.csv`(99MB)，经 `--config` 解析（不支持 `BACKTRADER_DATA_DIR`） | ⚠️ 非零退出并点名 `XAUUSD_M1.csv` |

小数据随目录走（`<leaf>/data/`，逐字节副本 + 漂移守卫）；**大数据不随目录复制**，缺失即 fail-closed 点名，
绝不静默联网补齐。`003` 是这一范式的既有实现。

## 3. live 索引

`live/000_live_certification/`：`binance_penetration`、`okx_penetration`、`simnow_penetration`
各 33 例 `cases/<ID>/{config.yaml,<ID>_strategy.py,run.py}`，内部拓扑保持迭代 41/42 原样；
同级 `optional16/` 为可选组件 16 拓扑矩阵（**不得拆到 `live/optional16/`**）。
命令 `python cases/<ID>/run.py` 干跑 / `--live [--allow-write] [--allow-dangerous]`；
私有 `.env` 与真实 `config.yaml` 不进仓库，因此副本内以 `env_keys_missing` 阻塞属设计结果。
`examples/unified/007_ctp/` 是 CTP 认证套件根与注册 runtime，位置见上表。

## 4. 旧→新映射与遗留登记

路径映射（迭代 43 R1–R4）：

| 旧路径 | 新路径 |
|---|---|
| `examples/001…017`（回测类同名目录） | `examples/backtest/<同名>` |
| `examples/012_1…015`、`examples/007_ctp` | `examples/unified/<同名>` |
| `examples/000_live_certification/**` | `examples/live/000_live_certification/**` |
| `examples/sample*`、`clean_bond_data.py`、`cross_exchange_replay_rules.py`、`strategy_candidate_approval.py`、`demo-approval-trust-root.pem`、`iteration41-runtime-inventory.json` | `examples/_support/…` |
| `examples/113013.csv`、`bond_index_000000.csv`、`DOGEUSDT_15m_*.csv`、`113013_strategy_result.png` | `examples/data/…` |

历史证据文档（`docs/_internal/**` 81 个文件）不改写，其旧路径按"已退役"读；
`AGENTS.md` 只追加现状说明。

## 5. 根目录遗留脚本与产物处理

根目录遗留清单最初有 **8 个脚本文件，按用途归为 7 组示例**（Bollinger 的训练和测试入口共用一个示例目录）。
其中 SMA、DOGE Bollinger、Binance 优化器、溢价率回测和 CryptoHFTData 已迁入 `backtest/018`–`022`；债券双因子脚本因策略行为不同，保留为独立的 `backtest/024_bond_two_factor_rank_legacy/`。目前剩余 1 个根目录脚本，继续整理混合模式示例。

| 当前路径 | 建议归属 | 迁移时必须处理 |
|---|---|---|
| `backtest/018_sma_crossover/` | 已完成 | 策略定义、运行入口、配置、README 与本地 CSV fixture 已归档在同一目录。 |
| `backtest/019_bollinger_band_doge/` | 已完成 | 共用 `examples/data/` 中的 DOGE 数据；训练和测试产物写入该叶子的忽略 `output/` 目录。 |
| `backtest/020_bollinger_binance_optimizer/` | 已完成 | Binance ZIP 数据由调用者提供；新增独立 `--output-dir`，不写到输入目录的父目录。 |
| `backtest/024_bond_two_factor_rank_legacy/optimize_strategy.py` | 已完成，独立保留 | 与 `001_multi_extend_data` 的并列排名、排序和过期订单处理不同；合并会改变结果，因此单独归档并说明差异。 |
| `backtest/021_premium_rate_crossover/` | 已完成 | 读取共享 `data/113013.csv`，生成图表写入独立输出目录；旧 PNG 保留在 reference。 |
| `backtest/022_cryptohftdata_sma/` | 已完成 | 远端历史数据仅在 `--run` 显式授权后请求；先检查可选 SDK 与 API-key 环境变量，缺少条件时阻塞。 |
| `mixed_mode_backtest.py` | `backtest/023_mixed_mode_backtest/` | 替换 `tests/datas/tick_data` 与 `tools/generate_test_data.py` 依赖为示例自有 fixture/生成器。 |

`examples/test_results/` 是本地运行产物，已加入 `examples/.gitignore`；其中已有文件保留在工作区，不作为示例输入提交。
`backtest/017_fnn_embedding/` 的模型缓存可能供默认回放使用，不能按普通临时文件删除；其结果 JSON/CSV/JSONL 与训练日志
需要另行区分“固定参考结果”和“本次运行输出”，并让新输出写到忽略的独立目录。`examples/data/113013_strategy_result.png`
是结果图而非输入数据，迁移时归入对应示例的参考报告或输出目录。三个 CSV 仍作为只读输入数据保留。

## 6. 保持现有边界的事项

1. 根 `examples/strategy-candidate-manifest.json` 留在原位置。其行指纹含 `resolved_example_path`，移动会要求受控重绑和审批材料更新。
2. 大数据统一 `--data-dir` 参数化另行处理（016/017 使用 `--config`）；`006` 的 `✓` 改纯 ASCII 输出；`001` 的 `log_data`→`log_bars` 参数名陈旧。
3. `012_1` 的 checkout-only `backtrader` 栅栏是受控约束，放宽需单独治理。
4. `live/000_live_certification` 的目录与私有凭据按迭代 41/42 设计绑定 checkout；保留 33-case 和相邻 `optional16/` 拓扑。

2026-10-12 修复复验：002 缺失 orderbook 默认路径已修复；006 必需 HTML 导出失败会返回失败。
完整的运行/明确拒绝/暂缓入口分类与安装来源检查见复制验收测试及迭代43修复复验报告。
历史 R6/R7 的完成声明不能替代本次结果；真实账户、HFT 对齐与大数据入口仍需各自验收。

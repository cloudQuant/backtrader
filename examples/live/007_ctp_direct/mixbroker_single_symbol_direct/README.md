# mixbroker_single_symbol_direct

rb2701 tick 输入的单品种混合策略（支持按 tick 数强制开平，专用于快速验证订单开平闭环）。

本目录位于 [`examples/live/007_ctp_direct`](../README.md)（**Direct 直连模式**，显式 `mode: direct`），对应 Gateway 版本位于 [`examples/live/007_ctp_gateway/mixbroker_single_symbol_gateway`](../../007_ctp_gateway/mixbroker_single_symbol_gateway/README.md)。

- **策略类**：`SingleSymbolMixStrategy`（[`single_symbol_mix_strategy.py`](./single_symbol_mix_strategy.py)）
- **合约**：`rb2701`（SHFE，tick=1.0，mult=10）
- **行情输入**：`ticks` / compression=`1`
- **装配路径**：`run.py` 经单一组合根 `create_direct_store` 创建 `DirectBtApiStore`（校验 `mode: direct`、绑定不可变 `LiveRunBinding(mode="direct")` 与 `ProcessModeFence`，零加载可选 SDK 服务子包），并由 `store.getbroker()` / `store.getdata()` 分别装配 `DirectBtApiBroker` 与 `DirectBtApiFeed`。
- **策略默认行为**：默认 `config.yaml` 配置 `max_roundtrips: 1`、`force_entry_after_ticks: 2`、`force_exit_after_ticks: 8`、`close_offset: auto`，开仓并平今 1 轮后自动优雅停止。

首次初始化、重启对账、待发单、UNKNOWN 人工核验和停止行为详解见[上级 README](../README.md)。

## 运行命令

```bash
# 1. 离线校验配置（不读取凭据、不联网）
python examples/live/007_ctp_direct/mixbroker_single_symbol_direct/run.py --dry-run

# 2. 首次初始化运行（仅在目录无 state/ 时执行一次；账户须空仓且无挂单）
python examples/live/007_ctp_direct/mixbroker_single_symbol_direct/run.py --first-init --env-file /path/to/.env

# 3. 常规重启运行（复用已有 state/ 对账并继续）
python examples/live/007_ctp_direct/mixbroker_single_symbol_direct/run.py --env-file /path/to/.env --run-seconds 600

# 4. 查看本目录持久化状态（只读、不含凭据）；若移动过目录须先 rebind --mode move
python -m backtrader.live_state show examples/live/007_ctp_direct/mixbroker_single_symbol_direct
```

## 目录文件

| 文件 | 内容 |
| --- | --- |
| `single_symbol_mix_strategy.py` | `SingleSymbolMixStrategy`；与 [`examples/backtest/007_ctp/mixbroker_single_symbol`](../../../backtest/007_ctp/mixbroker_single_symbol/README.md) 对应 |
| `run.py` | 校验 `mode: direct` 与日历门禁、读取凭据（不打印）、经 `create_direct_store` 装配 Store/Broker/Feed、启动 `RunStatusWriter` 与 TradeLogger、带超时优雅停止并输出摘要 |
| `config.yaml` | `mode: direct`、合约与交易所、CTP 前置档案、`calendars.root` 与 `feed_scope`、写入准入、Broker 直连参数、feed 与策略参数（`order_exectype: limit`、`close_offset: auto`） |

## 2026-11-23 验证记录

- **离线 `--dry-run`（`PACKAGE` + `CLI_DRY_RUN`）**：**PASS**（仓库外 `C:\Windows\Temp`、无 `PYTHONPATH` 下退出码 `0`）。
- **离线全链路 E2E（`FAKE` / `INTEGRATION_SIM`）**：**PASS**（缺凭据拒启 `rc=2` → `--first-init` 落盘 `identity.json` v2 `mode=direct` `rc=0` → 重启 `rc=0` → 目录迁移拦截 `strategy_dir_mismatch` → `rebind --mode move` 后重启 `rc=0`，0 个可选 SDK 服务子包加载）。
- **SimNow 模拟盘实测（`SIMNOW_DEMO`）**：**PASS（退出码 `0`，`outcome=STOPPED`，2026-11-23 14:35）**：`--first-init`（v2 `mode=direct`）后默认配置实盘运行：未 LIVE 前正确拒单并退避（`target_feed_not_live`），`rb2701 -> LIVE` 后买开 `3002.00`（1 手）→ 卖平今 `3001.00`（1 手），完成 1 轮闭环并恢复空仓。
- **真实券商生产账户（`REAL`）**：**NOT_RUN**（SimNow 结果仅证明模拟账户行为，不代表真实资金账户验收）。

## 状态与目录约束

运行后本目录会生成本地忽略的 `state/`（`identity.json`、`sequence.json`、`pending.json`、`waiting_orders.json`、`run_status.json`、`last_run.json`、`audit.log`）和 `logs/`（`current_position.yaml` 对账基线及 TradeLogger 运行日志）。不要在两个进程中同时运行同一目录；需要并行时请复制目录并分别执行 `--first-init`。

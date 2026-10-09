# 012_2 — 盘口事件驱动跨所永续 taker-taker IOC（OKX + Binance Demo）

独立候选 `taker_taker_ioc_event_arbitrage`（OKX `BTC-USDT-SWAP` × Binance `BTCUSDT`，
盘口事件驱动的 taker-taker IOC 配对）。研究状态为 **RESEARCH_REJECTED**
（证据级 `CALIBRATION_ECONOMIC_SCREEN_REJECTED_HOLDOUT_NOT_CONSUMED_HFT_FAILED`，
`hft_label=event_driven`）；本目录提供的是**技术贯通验收路径**，不产生研究/盈利结论，
也不改变 HFT 未准入标注。

## 运行方式（迭代42 标准四件套）

```
README.md + config.yaml + event_driven_strategy.py + run.py
```

```text
python run.py                       # 干跑自检：候选配置 + entry 段 + 凭据 env 名（不联网）
python run.py --replay [--scenario profitable]   # 离线公式 fixture（0 网络 / 0 写单）
python run.py --live --allow-write --mechanical-smoke [--run-seconds 180]
                                    # OKX+Binance Demo 有界机械配对（技术验收）

# 等价的模块调用形式（从仓库根目录）：
python -m examples.012_2_event_driven_cross_exchange.run --replay
python -m examples.012_2_event_driven_cross_exchange.run --live --allow-write --mechanical-smoke
```

- 本示例只提供技术贯通验收，不构成未来盈利保证，也不证明可持续盈利。

- 解释器要求：本示例的 dry/`--replay` 亦会加载 dev SDK（`bt_api_py` umbrella），请使用
  `C:/anaconda3/python.exe`（3.11，dev SDK 已接入）；系统默认 `python`（3.14）会解析到
  旧 site-packages 副本并在导入期报错。live 层同此解释器。
- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN。
- 证据写入 `evidence/<run_id>/`（run.json + report.json，git-ignored）；
  报告带 `MECHANICAL_DEMO_SMOKE_NOT_RESEARCH` 边界标记。
- 凭据只按名从 checkout 根 `.env` 读取（`OKX_DEMO_*` / `BINANCE_DEMO_*`）；
  config.yaml 只含 env 名称，不含密钥。**不把 `.env` 注入进程环境**（避免其中的
  代理提示影响 SDK 的 HTTP 层；代理如确需使用，请在宿主机层面配置）。

## Demo 准入语义

- 候选为 RESEARCH_REJECTED 且无签名 demo 审批租约 → 仅开放 operator 确认的
  **本地有界 Demo 会话**（`--mechanical-smoke` 仅作显式确认开关；本候选没有
  012_1 的"机械配对"工具，事件引擎在 180s 有界窗口内按自身条件运行并受
  风险/查询对账约束）；
- 无 `--allow-write` / 无 `--mechanical-smoke` 一律 fail-closed；
- 命令运行限定在仓库内（demo 需 canonical manifest 绑定），不复制目录运行。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `event_driven_strategy.py` | 事件驱动引擎与执行状态机（`CrossExchangeArbitrageStrategy`、`EventArbitrageEngine`、`EventPathQualification`、`EventDrivenRisk`） |
| `legacy_runner.py` | 旧引擎入口（dry 校验、`run_replay`、`_run_network_impl` demo/shadow 网络路径） |
| `strategy_candidate_approval.py` + `demo-approval-trust-root.pem` | Vendored 准入策略与审批信任根（字节一致副本） |
| `strategy-candidate-manifest.json` | 候选清单（哈希绑定；刷新脚本：`scripts/refresh_cross_exchange_local_manifests.py`） |
| `runtime/` + `run_runtime.py` | 迭代41 LOCAL_REPLAY_ONLY bt-runtime 登记路径（保留至收尾轮统一处置） |

## 边界

- 真实成交往返验收 = Demo 机械配对的技术贯通证据；不构成策略有效性、盈利、
  生产或 HFT 延迟准入结论；HFT 证据级保持 `HFT_FAILED / NOT_ADMITTED`。
- 历史冻结记录（迭代21/30）不被本迭代改写；接口差异以本 README 与
  `docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/迭代计划.md` 为准。

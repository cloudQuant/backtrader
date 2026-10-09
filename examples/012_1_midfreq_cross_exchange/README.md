# 012_1 — 跨所永续合约中频均值回归（OKX + Binance Demo）

独立候选 `robust_executable_basis_mean_reversion`（OKX `BTC-USDT-SWAP` × Binance `BTCUSDT`，
中频稳健基差均值回归）。研究状态为 **RESEARCH_REJECTED**（迭代21经济筛选未通过，
`qualification-v3.json` 校准窗口已于 2026-10-07 到期）；本目录提供的是
**技术贯通验收路径**，不产生研究/盈利结论。

## 运行方式（迭代42 标准四件套）

```
README.md + config.yaml + cross_exchange_strategy.py + run.py
```

```text
python run.py                       # 干跑自检：候选配置 + entry 段 + 凭据 env 名（不联网）
python run.py --replay [--scenario profitable]   # 离线公式 fixture（0 网络 / 0 写单）
python run.py --live --allow-write --mechanical-smoke [--run-seconds 600]
                                    # OKX+Binance Demo 有界机械配对（技术验收；
                                    # 观测时长需 ≥435s，上限 600s）

# 等价的模块调用形式（从仓库根目录）：
python -m examples.012_1_midfreq_cross_exchange.run --replay
python -m examples.012_1_midfreq_cross_exchange.run --live --allow-write --mechanical-smoke
```

- 本示例只提供技术贯通验收，不构成未来盈利保证，也不证明可持续盈利。

- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN。
- 证据写入 `evidence/<run_id>/`（run.json + report.json，git-ignored）；
  报告带 `MECHANICAL_DEMO_SMOKE_NOT_RESEARCH` 边界标记。
- 凭据只按名从 checkout 根 `.env` 读取（`OKX_DEMO_*` / `BINANCE_DEMO_*`）；
  config.yaml 只含 env 名称，不含密钥。**不把 `.env` 注入进程环境**（避免其中
  的代理提示影响 SDK 的 HTTP 层；代理如确需使用，请在宿主机层面配置）。

## Demo 准入语义

- 候选为 RESEARCH_REJECTED 且无签名 demo 审批租约 → 仅开放
  `--mechanical-smoke`（operator 确认的**本地有界 Demo 机械配对**：
  单轮、有界数量/名义、场内侧受理与独立查询对账）；
- 无 `--allow-write` / 无 `--mechanical-smoke` 一律 fail-closed；
- 命令运行限定在仓库内（demo 需 canonical manifest 绑定），不复制目录运行。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `cross_exchange_strategy.py` | 候选策略与引擎（基差/资格/风险/执行状态机；`CrossExchangeArbitrageStrategy`） |
| `legacy_runner.py` | 旧引擎入口（dry 校验、`run_replay`、`_run_network_impl` demo/shadow 网络路径） |
| `strategy_candidate_approval.py` + `demo-approval-trust-root.pem` | Vendored 准入策略与审批信任根（字节一致副本） |
| `strategy-candidate-manifest.json` + `qualification-v3.json` | 候选清单/资格工件（哈希绑定；刷新脚本：`scripts/refresh_cross_exchange_local_manifests.py`） |
| `runtime/` + `run_runtime.py` | 迭代41 LOCAL_REPLAY_ONLY bt-runtime 登记路径（保留至收尾轮统一处置） |

## 边界

- 真实成交往返验收 = Demo 机械配对的技术贯通证据；不构成策略有效性、盈利、
  生产或 HFT 结论（本候选 `hft_label=not_applicable`）。
- 历史冻结记录（迭代21/26/30）不被本迭代改写；接口差异以本 README 与
  `docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/迭代计划.md` 为准。

# 013_3 — SA 中频 SimNow 示例（迭代42 标准四件套）

本目录是 `iter22-sa-v0` 候选（CZCE 纯碱 SA 中频策略）的可执行参考实现，
按迭代42 标准形态交付：**README.md + config.yaml + sa_midfreq_strategy.py + run.py**
（唯一运行入口），另含运行必需的内部模块（下表）。研究状态保持
`RESEARCH_NOT_ESTABLISHED`；本示例证明的是技术贯通，不是收益或策略有效性结论。

## 运行方式

实时 SimNow 路径要求 CPython 3.11（例如 `C:/anaconda3/python.exe`）与
dev 版 SDK 源码（`BT_API_PY_ROOT`，默认 `D:/bt_api_py`）：

```text
python run.py                        # 干跑自检：仅校验配置结构与凭据 env 名（不联网）
python run.py --replay               # 离线回放：本地冻结 fixture，零网络零写入
python run.py --live --allow-write   # SimNow 模拟账户：有界真实成交往返
```

- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN。
- 每次 replay/live 运行在 `evidence/<run_id>/` 写 JSON 证据（git-ignored）。
- 凭据只按名从 checkout 根 `.env` 读取（`CTP_BROKER_ID` 等）；config.yaml 不含任何密钥。

## live 语义（要点）

- **写准入**：仅经 SDK 窄口径 registered-sim 准入（精确 SimNow 前置白名单、一次性武装、
  逐笔 capability 传递）；Store/managed/production 写路线保持关闭。
- **前端选择**：1–8 组完整 MD/TD pair；TCP 探测仅作候选筛选（每端 ≥1/3 成功），
  白名单内的对优先，按最大成功中位延迟排序；准入按序逐对尝试（每次全新会话，
  只在任何写入之前）；一旦武装成功不再切换环境。
- **账户前置**：试点要求账户无持仓、无活动委托（不满足即 BLOCKED）；有界策略
  （`policy.max_actions` 等）；运行结束自动平仓与对账。
- **触发来源**：`--drill` 为工程演练窗口（`purpose=engineering_smoke` + 工程触发单，
  显式 `drill` 标记，缩小预热并放宽时段窗口），自然信号运行不加演练；
  drill 只在"无自然尝试、无未决/UNKNOWN、预检通过"下成立。
- **MD 兼容**：本账号所用 SimNow 前置以请求编号 0 回应 MD 登录（
  `live_market_data.allow_zero_login_response=true`，仅开放行情订阅身份；
  TD 身份仍严格校验）。
- 离线回放与 live 的证据层级严格分开；replay 不能替代真实账户验收。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `simnow_direct.py` | 直连 registered-sim 执行层：前端选择、Store/包装器子类（仅覆写被关闭的 3 个入口）、准入/冻结/解除 |
| `legacy_runner.py` | 冻结候选引擎与 `--replay` 实现（含冻结校验、回放、证据写入） |
| `features.py` / `signal_model.py` / `risk.py` / `reporting.py` / `account_lock.py` | 特征、信号融合、日内风控、证据读写、账户锁 |
| `runtime-ctp-private/` | 受保护私有运行时配置（git-ignored），处置在收尾轮逐项决定 |

已退役（2026-10-11 精简轮）：`runtime/`、`run_runtime.py`、`runtime-managed-replay/`、
`run_managed_replay_runtime.py`（迭代41 登记路由的源树副本）与 `admission_receipt_tool.py`、
`operator_readiness.py`、`pilot_supervisor.py`（迭代22 离线工具/监督器）已删除；对应登记从
`backtrader_runtime` 注册表与 `iteration41-runtime-inventory.json` 移除。`run.py` 的三模式
（dry/`--replay`/`--live`）不依赖上述文件。包内离线 fake-provider L2 fixture 与机械化管理回放
登记不受影响。

## 证据与边界

- 现场证据：各 `evidence/<run_id>/`（run.json、风控状态、日志、回放报告）。
- 边界标签：回放=`LOCAL_REPLAY_ONLY`；live=真实 SimNow 模拟账户、有界写入、
  非盈利/非生产结论；HFT/延迟结论不适用。


## 运行层选择（迭代 43）

本目录的通道由 `config.yaml` 的 `entry.tier` 决定，命令行模式参数只能**保持或降低**它，不能上调：

| `entry.tier` | 无模式参数 | `--dry` | `--replay` | `--live` |
| --- | --- | --- | --- | --- |
| 未声明 | `dry`（与迭代 43 之前逐字一致） | `dry` | `replay` | `live` |
| `dry` | `dry` | `dry` | `dry` | BLOCKED `config_tier_conflict` |
| `replay`／`backtest` | `replay` | `dry` | `replay` | BLOCKED `config_tier_conflict` |
| `live` | `live` | `dry` | `replay` | `live` |

- 规范值 `dry | replay | live`；`backtest` 是 `replay` 的文档别名，证据里记 `effective_tier: replay`。
- 非法值、错误类型或 `entry: null` 在**任何 handler 与 provider 副作用之前**返回
  BLOCKED `config_tier_invalid`，绝不回落到 live。
- 输出 JSON 的 `tier` 字段记录 `config_tier / cli_tier / effective_tier / tier_selection_reason`，
  `write_grant_result` 记录写授权结果。`--allow-write` 与选层正交：判定器不读它，
  本目录原有的写准入条件一字未改。
- 判层依赖本目录自带的 `entry_tier.py`（`examples/_support/entry_tier.py` 的逐字节副本，
  由 `tests/unit/test_examples_self_contained.py` 漂移守卫），因此整个目录被复制到别处后
  仍能自行判层。

声明方式（追加到本目录 `config.yaml` 末尾）：

```yaml
entry:
  tier: replay   # dry | replay | live（backtest 为 replay 别名）
```

本目录的 live 通道先校验解释器（`live_tier_requires_python_3_11`），再要求显式 `--allow-write`，因此声明 `tier: live` 而无模式参数不会触达任何 provider；无写观察通道由迭代 43 的 R5b 轮补齐。

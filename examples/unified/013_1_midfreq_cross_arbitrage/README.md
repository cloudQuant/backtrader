# 013_1 — 中低频跨品种套利 m/RM（迭代42 标准四件套）

本目录是"豆粕 m × 菜粕 RM"中低频跨品种价差套利示例，按迭代42 标准形态交付：
**README.md + config.yaml + pair_arbitrage_strategy.py + run.py**（唯一运行入口），
另含运行必需的内部模块（下表）。本示例证明的是技术贯通，不是收益或策略有效性结论；
合成回放不构成未来盈利保证，真实 SimNow 运行也不证明可持续盈利。

## 运行方式

实时 SimNow 路径要求 CPython 3.11（例如 `C:/anaconda3/python.exe`）与
dev 版 SDK 源码（`BT_API_PY_ROOT`，默认 `D:/bt_api_py`）：

```text
python run.py                        # 干跑自检：仅校验配置结构与凭据 env 名（不联网）
python run.py --replay               # 离线回放：本地冻结 fixture，零网络零写入
python run.py --live --allow-write   # SimNow 模拟账户：m/RM 双腿有界真实成交往返
```

- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN。
- 每次 replay/live 运行在 `evidence/<run_id>/` 写 JSON 证据（git-ignored）。
- 凭据只按名从 checkout 根 `.env` 读取（`CTP_BROKER_ID` 等）；config.yaml 不含任何密钥。

也可从仓库根目录经迭代41 登记路径运行同一冻结回放（`LOCAL_REPLAY_ONLY`）：

```powershell
bt-runtime run --strategy-dir examples/unified/013_1_midfreq_cross_arbitrage/runtime
```

## live 语义（要点）

- **写准入**：仅经 SDK 窄口径 registered-sim 准入（精确 SimNow 前置白名单、一次性武装、
  逐笔 capability 传递）；Store/managed/production 写路线保持关闭。
- **双腿武装**：一次准入只授权一个合约，m 腿与 RM 腿在每次真实写入之前按自身
  preflight 身份切换武装（先解除、再武装，绝不在写入之后切换前端），
  `arm_history` 记录每次切换；准入阶段对两条腿分别演练武装后才开始运行。
- **前端选择**：1–8 组完整 MD/TD pair；TCP 探测仅作候选筛选（每端 ≥1/3 成功）；
  时段内优先 standard、时段外优先 7x24；按最大成功中位延迟排序；准入按序逐对尝试
  （每次全新会话，只在任何写入之前）；一旦武装成功不再切换环境。
- **账户前置**：试点要求账户无持仓、无活动委托（不满足即 BLOCKED）；两条腿的合约
  元数据（tick/乘数）逐项与 `instrument_metadata` 核对。
- **执行修复（迭代42 §4 三类缺陷）**：平仓 offset 由交易所元数据推导
  （SHFE/INE=`close_today`，DCE/CZCE=`close`，品种前缀启发仅保留为离线回放默认）；
  一档盘口缺失时拒绝下单并 halt（不再回退 close 价盲发）；订单超时/持有计时改用
  本机单调时钟（不再依赖数据时钟）。
- **触发来源**：`--drill` 为工程演练窗口（一次性显式触发、`max_pairs=1`、按
  `drill.hold_seconds` 确定性平仓、缩小 z-score 观察周期）；自然信号运行不加演练。
- **MD 兼容**：本账号所用 SimNow 前置以请求编号 0 回应 MD 登录
  （`live_market_data.allow_zero_login_response=true`，仅开放行情订阅身份；
  TD 身份仍严格校验）。
- 离线回放与 live 的证据层级严格分开；replay 不能替代真实账户验收。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `simnow_direct.py` | 直连 registered-sim 执行层（013_3 同源字节副本）：前端选择、Store/包装器子类、准入/冻结/解除、双腿武装模板 |
| `legacy_runner.py` | 冻结回放引擎与 `--replay` 实现（原 `run.py` 内容）；另被 `run_runtime.py` 复用 |
| `ctp_example_support.py` | 007 同源字节副本（历史支持模块；仅 `legacy_runner` 复用其配置读取） |
| `runtime/`、`run_runtime.py` | 迭代41 的 LOCAL_REPLAY_ONLY bt-runtime 登记路径 |

## 证据与边界

- 现场证据：各 `evidence/<run_id>/`（run.json：准入/预检/订单/对账/诊断）。
- 边界标签：回放=`SYNTHETIC_REPLAY_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE`；
  live=真实 SimNow 模拟账户、有界写入、非盈利/非生产结论。
- 成交判定按会话归属（仅统计本次运行订单对应的 trades 行），并要求双腿
  entry/close 均补齐、终态无持仓、无活动委托。

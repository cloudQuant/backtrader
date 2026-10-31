# 052 — Binance USD-M Demo 直接 paper 往返（迭代 52 首个竖切）

本目录是迭代 52 的第一条真实 paper 竖切：普通 Backtrader `Strategy` 通过统一配置、
`bt_api_runtime` 的受控直接装配和既有 `BtApiStore` / `BtApiBroker` 执行链，在 Binance
USD-M **Demo（外部模拟账户）** 上完成一笔有界 LIMIT 往返（挂单 → 确认 → 撤单；若部分成交则
reduce-only 平仓），并在有界会话内正常停机。

四件套：`README.md + config.yaml + binance_demo_roundtrip_strategy.py + run.py`；
`entry_tier.py` 是迭代 43 的可复制判层副本（运行必需，非第二入口）。

## 运行方式

`config.yaml` 是迭代 52 唯一的 schema-v2 用户配置：`mode: paper`、`environment: paper`，
九个符号引用 + `strategy_parameters` + `requested_capabilities`。凭据只按 **变量名** 从
checkout 根 `.env`（或 `--env-file` 指定的文件）读取，配置模板不含任何秘密值。

```text
python run.py                 # 离线校验：只解析 schema/策略参数，不读凭据、不联网、不导入 provider
python run.py --live          # BLOCKED / write_not_authorized（写授权是独立门槛）
python run.py --live --allow-write
```

- 退出码：`0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN`。
- 证据写入本目录 `evidence/`（git-ignored），字段含 `entry_tier`、`report.strategy_facts`、
  broker/store 的 execution summary 与停机状态；不含凭据值。
- 运行需要 dev SDK 源码与新的 runtime/contract 源码（`BT_API_PY_SRC`、`BT_API_RUNTIME_SRC`、
  `BT_API_CONTRACT_SRC`，默认 `D:/bt_api_py` 下的对应目录）。

## live 语义（要点）

- **模式与权限分离**：`mode: paper` 绑定 Demo 账户环境；`--allow-write` 与一次性有界
  `DirectWriteGrant`（run id、账户环境、symbol、到期时间、最大订单数、最大名义金额）是独立写门槛。
  生产写入未授权，`allow_live_write` 在本目录恒为 `false`。
- **同一策略源码**：策略只做业务决策（挂单价、数量、超时、撤单/减仓），不判断模式、provider、
  endpoint 或账户；切换环境由 `config.yaml`（profile/route/账户引用）与装配入口承担。
- **有界往返**：单笔 LIMIT 挂在市价下方 200 bps，6 秒后撤单；部分成交则 reduce-only 市价平仓；
  45 秒硬超时；会话级 deadline 兜底。订单写入不重试，UNKNOWN 不自动重发。
- **风控**：`require_account_risk=true`，Demo 账户必须无持仓、无活动委托且可初始化风险基线；
  订单数量/名义金额与 grant 上限由配置和代码双重约束。
- **停机**：Broker → Store 逆序关闭并记录 `broker_shutdown_state`、`store_connected`；
  进程退出不冒充账户清理成功。

## 运行层选择（迭代 43）

本目录的通道由 `entry_tier.decide` 解析；`config.yaml` 不声明 `entry.tier`（避免与 schema-v2
契约冲突），因此命令行 `--live` 是唯一升层方式：无 flag 为 `dry`，`--live` 为 `live`，
`--dry` 为离线校验。任何非法/冲突声明都在 provider 副作用之前 `BLOCKED`。

- `entry_tier` 是通道决策；既有 `tier` 是结果层级标签（本目录证据里是 `PASS/FAILED/...`），
  两者不互相覆盖。
- `--allow-write` 与选层正交：判层器不读它，写准入在选层之后独立执行。

## 证据与边界

- 本目录只证明：统一配置/受控装配/真实 Backtrader 执行链在 Binance Demo 外部模拟账户上的
  一笔有界往返与正常停机。它不是收益、延迟、HFT 或生产就绪结论。
- 不改变 `examples/live/000_live_certification` 三场所 99 个正式 case 的身份、授权前置和历史
  状态；本目录不是正式 case 的替代或升级。
- 旧 `backtrader_runtime` / `legacy_runner` 未被本目录使用。

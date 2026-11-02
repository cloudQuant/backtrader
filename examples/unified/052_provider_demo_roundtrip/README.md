# 052 — provider Demo paper 示例（迭代 52；当前接线迁移中）

本目录曾以一份普通 Backtrader `Strategy` 的统一 paper 交易路径为迭代 52 竖切目标；以下原设计与命令记录不等于当前验收状态。当前入口仍在迁移，不能据此声称往返交易、连接就绪、完整 paper/live 能力或真实账户验收已完成。

## 当前接线状态（2026-11-01）

- 非 CTP 的 `run.py` 预检分支要求宿主显式注入精确 `ProviderConfigurationSelection`，由 SDK 返回 `ProviderConfiguration` 后调用 `bt_api_py.managed_runtime_composition.compose_read_only_runtime(configuration)`；预检结束只关闭一次组合。命令行本身不会签发或推导 selection，因此单独运行 `--preflight-only` 不会创建可用路由。配置选择不证明账户、连接或行情就绪；缺少精确只读 route owner 或 SDK 只读能力时应保持 unavailable。
- CTP 的 `simnow_runner.py` 仍经本地 `simnow_paper.compose_runtime(..., access_mode="read_only")` 组合，并要求宿主 `runtime_binding`；它尚未接入上述 SDK 只读入口。这是当前两条入口的结构性差异，后续统一时需保留 CTP 专有配置/原生能力由 SDK 管理的边界。
- managed execution 仍是独立能力：需要可信宿主提供的 runtime binding、写授权来源、精确 operator grant 及执行授权。配置、`paper/live` 模式或只读预检都不授予写权限；缺能力时必须返回 unavailable。
- 本轮仅做源码接线与文档更新，没有运行示例、测试或账户操作。当前状态不构成 BT01/BT02、完整 I52 或任何真实账户验收。

以下场景表与其后的历史运行命令、语义和证据表述保留为早期实现/设计记录，不代表当前入口可运行或已经复验。
场景由配置中的 `strategy_parameters.venue` 选择（代码拥有的 provider profile 负责映射到
SDK venue key、账户币种、凭据变量名与 ledger 场所），策略源码不判断 venue/provider/endpoint：

| 公开模板 | venue | product | 账户环境 |
| --- | --- | --- | --- |
| `config.yaml` | `BINANCE` | BTCUSDT（USD-M） | Binance Demo |
| `config.okx.yaml` | `OKX` | BTC-USDT-SWAP | OKX Demo |

历史目录约定（未按当前入口复核）：`README.md + config.yaml + provider_demo_roundtrip_strategy.py + run.py`；
`config.okx.yaml` 是第二个公开模板；`entry_tier.py` 是迭代 43 的可复制判层副本（运行必需，非第二入口）。

## 历史运行命令（不代表当前可运行）

```text
python run.py                                   # 离线校验（Binance 模板），不读凭据、不联网
python run.py --config config.okx.yaml          # 离线校验（OKX 模板）
python run.py --live                            # BLOCKED / write_not_authorized
python run.py --live --allow-write              # Binance Demo 有界往返
python run.py --config config.okx.yaml --live --allow-write   # OKX Demo 有界往返
python run.py --config config.simnow.yaml --live --allow-write \
  --private-config ../013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml  # SimNow registered-sim
```

SimNow 分支是 **checkout-bound** 的：它按路径复用 `013_3/simnow_direct.py`，需要
CPython 3.11、dev SDK 源码、私有 `ctp:` 配置（1–8 组完整 MD/TD pair）和 `.env` 中的
`CTP_*` 凭据；dry/离线不会读取这些私有输入。接受运行使用 1 手 SA701 可成交 GFD 开仓 +
reduce-only GFD 平仓；registered-sim 的**撤单**路径受跨会话 OrderRef/typed cancel 限制，
尚未作为本轮 PASS 依据；CTP fee 尚未投影。详见 `docs/_internal/.../evidence/iteration52-c2-simnow-paper-2026-10-31.md`。

- 退出码：`0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN`。
- 证据写入本目录 `evidence/`（git-ignored）；含 `entry_tier`、venue、strategy facts、
  broker/store execution summary 与停机状态，不含凭据值。
- 凭据只按变量名从 checkout 根 `.env`（或 `--env-file`）读取；两场所共用同一个账户
  execution ledger 时，需用 `--order-journal` 指向既有 ledger（默认由 SDK 推导；冲突时
  fail closed，不迁移、不删除）。
- 运行需要 dev SDK 源码与新的 runtime/contract 源码（`BT_API_PY_SRC`、`BT_API_RUNTIME_SRC`、
  `BT_API_CONTRACT_SRC`，默认 `D:/bt_api_py` 下的对应目录）。

## 历史 live 设计要点（待当前实现复核）

- **模式与权限分离**：`mode: paper` 绑定 Demo 账户环境；`--allow-write` 与一次性有界
  `DirectWriteGrant`（run id、provider/环境/symbol、到期时间、最大订单数、最大名义金额）
  是独立写门槛。生产写入未授权，`allow_live_write` 在本目录恒为 `false`。
- **同一策略源码**：策略只做业务决策（挂单价、数量、超时、撤单/减仓）；数量按
  `notional_usdt / (price × contract_value)` 换算，`quantity_unit` 由配置声明。
  切换 provider 只改配置与 profile 映射，不改策略文件。
- **有界往返**：Binance 模板用 GTC LIMIT 挂在市价下方 200 bps、6 秒后撤单；OKX 模板用
  可成交 IOC LIMIT 开仓并以 tick 对齐的 reduce-only 限价 IOC 平仓。部分成交则 reduce-only 平仓；
  45 秒硬超时；会话级 deadline 与 runtime idle pump 兜底。订单写入不重试，UNKNOWN 不自动重发。
- **恢复**：runtime 在写前对账，并在 idle pump / shutdown 前用独立 provider 查询把
  provider 已终态但 journal 未确认的订单写成终态（只查/只写 journal，不重发、不撤单）；
  `close_delay_seconds` / `recovery_grace_seconds` 为后续写与停机留出有界确认窗口。
- **风控**：`require_account_risk=true`，风险快照 max age 30s；账户必须可交易、无活动订单、
  可初始化/读取风险基线。订单数量/名义金额由配置与 grant 双重约束。
- **停机**：Broker → Store 逆序关闭并记录 `broker_shutdown_state`、`store_connected`；
  进程退出不冒充账户清理成功。

## 历史运行层选择记录（迭代 43）

本目录的通道由 `entry_tier.decide` 解析；模板不声明 `entry.tier`（避免与 schema-v2 契约冲突），
因此命令行 `--live` 是唯一升层方式：无 flag 为 `dry`，`--live` 为 `live`，`--dry` 为离线校验。
任何非法/冲突声明都在 provider 副作用之前 `BLOCKED`。

- `entry_tier` 是通道决策；既有 `tier` 是结果层级标签（本目录证据里是 `PASS/FAILED/...`），
  两者不互相覆盖。
- `--allow-write` 与选层正交：判层器不读它，写准入在选层之后独立执行。

## 历史证据与边界说明
> 本节中的“已完成”表述沿用旧 README 的历史文字；本次没有重新核实对应账户、源码或验收记录，不能据此判断当前代码状态。


- 本目录已用**同一策略源码**在 Binance USD-M Demo（挂/撤）与 OKX SWAP Demo（IOC 开/平）
  完成有界 paper 往返；这是两个外部模拟账户场所的证据，不是收益、延迟、HFT 或生产就绪结论。
  SimNow、installed wheel 与旧 runtime 退役仍为后续验收。
- 不改变 `examples/live/000_live_certification` 三场所 99 个正式 case 的身份、授权前置和历史
  状态；本目录不是正式 case 的替代或升级。
- 旧 `backtrader_runtime` / `legacy_runner` 未被本目录使用。

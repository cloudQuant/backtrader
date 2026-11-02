# 013_3 — SA 中频 SimNow 示例（迭代42 标准四件套）

本目录是 `iter22-sa-v0` 候选（CZCE 纯碱 SA 中频策略）的可执行参考实现，
按迭代42 标准形态交付：**README.md + config.yaml + sa_midfreq_strategy.py + run.py**
（唯一运行入口），另含运行必需的内部模块（下表）。研究状态保持
`RESEARCH_NOT_ESTABLISHED`；本示例证明的是技术贯通，不是收益或策略有效性结论。

## 运行方式

当前可用的离线入口与实时能力状态：

```text
python run.py --dry      # 离线结构自检；不启动 provider
python run.py --replay   # 本地冻结 fixture；零网络、零写入
python run.py --live     # CLI 无宿主绑定，返回 MANAGED_RUNTIME_BINDING_UNAVAILABLE
```

- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN。
- CLI 只有在宿主显式注入 exact `bt_api_py` `ManagedRuntimeBinding` 后才能进入实时预检；缺少绑定时不读取 provider 配置，也不启动 provider。纯命令行入口当前无法提供该绑定。
- 只读路径经 `bt_api_py` provider-configuration 与 managed-runtime facade 读取中立账户会话 DTO；Backtrader 不解析 CTP 前端或原生回报字段。当前没有已验证的数据时钟，策略和 Feed 不会启动。
- `--allow-write` 只是请求标记。写模式还要求宿主分别注入 SDK authorization source 和 `OperatorWriteGrant`，并由 provider/runtime 验证；当前实时 Feed 时钟能力不可用，因此本示例不下单。
- `--backend service` 对应的旧 `backtrader_runtime` 已退役，当前返回 `BACKTRADER_RUNTIME_CAPABILITY_UNAVAILABLE`。
- 历史证据保留原样；它们不表示当前入口可以建立账户会话或完成交易。

## 当前实时能力边界

- 旧 `simnow_direct.py` 直连、CTP Store 子类、原生字段解析和 registered-sim arm 路径已从三个示例入口移除。
- 实时配置只通过 `bt_api_py` 的 provider-configuration facade 选择；SDK 内部负责 CTP 配置/profile 校验、凭据封存和 route composition。Backtrader 不获取凭据值、CTP client 或 native DTO。
- 只读预检需要已就绪宿主传入精确 `ManagedRuntimeBinding`。它最多读取中立 `AccountSessionSnapshot`；由于当前未提供经验证的 Feed clock，运行结果仍为 BLOCKED，Strategy 不会启动。
- 写入需要独立的 SDK authorization source 与有界 `OperatorWriteGrant`；mode、profile、账户 ready 状态或 `--allow-write` 都不构成授权。当前策略写路径保持 unavailable。
- 本地 `--dry` 和冻结 fixture `--replay` 保留；它们不证明实时行情、账户状态、成交或盈利能力。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `provider_runtime.py` | 本地薄适配器；只调用 `bt_api_py` 公共 provider-configuration 与 managed-runtime facade。 |
| `legacy_runner.py` | 冻结回放 fixture；CLI 只允许 replay，旧网络 helper 不由 `run.py` 调用且不可作为运行入口 |
| `features.py` / `signal_model.py` / `risk.py` / `reporting.py` / `account_lock.py` | 特征、信号融合、日内风控、证据读写、账户锁 |
| `runtime-ctp-private/` | 受保护私有运行时配置（git-ignored），处置在收尾轮逐项决定 |

已退役（2026-10-11 精简轮）：`runtime/`、`run_runtime.py`、`runtime-managed-replay/`、
`run_managed_replay_runtime.py`（迭代41 登记路由的源树副本）与 `admission_receipt_tool.py`、
`operator_readiness.py`、`pilot_supervisor.py`（迭代22 离线工具/监督器）已删除；对应登记从
`backtrader_runtime` 注册表与 `iteration41-runtime-inventory.json` 移除。`run.py` 的三模式
（dry/`--replay`/`--live`）不依赖上述文件。包内离线 fake-provider L2 fixture 与机械化管理回放
登记不受影响。

## 证据与边界

- 新入口证据只记录本地回放结果或中立能力状态；历史账户/订单证据保留原样，不代表当前路径已验收。
- 边界标签：回放保留各自既有的合成/本地证据标签；live 当前仅用于显式宿主绑定的只读能力预检，策略、行情时钟和写入均未接通。
## 运行层选择（迭代 43）

本表描述宿主已注入实时绑定后的配置选层。直接命令行不提供该绑定；显式 `--dry` 与 `--replay` 可离线执行，需要读取 `entry.tier` 的默认/实时调用会在配置解析前返回绑定能力状态。

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
- 输出 JSON 的 `entry_tier` 字段记录 `config_tier / cli_tier / effective_tier / tier_selection_reason`；`write_grant_result` 只记录请求/验证状态，不从模式或配置签发权限。
- 注意 `entry_tier` 与既有 `tier` 是两个字段：`tier` 是迭代 42 起记录的**结果层级**标签
  （例如 `fill_round_trip`、`observation_only_tick_arrival`），迭代 43 的历史证据按它判读，
  因此通道决策一律写进 `entry_tier`，绝不覆盖 `tier`。
- 判层依赖本目录自带的 `entry_tier.py`（`examples/_support/entry_tier.py` 的逐字节副本，
  由 `tests/unit/test_examples_self_contained.py` 漂移守卫），因此整个目录被复制到别处后
  仍能自行判层。

声明方式（追加到本目录 `config.yaml` 末尾）：

```yaml
entry:
  tier: replay   # dry | replay | live（backtest 为 replay 别名）
```

本目录的实时入口当前是 capability preflight，不是下单验收通道。没有宿主绑定时，入口在读取 provider 配置前返回 `MANAGED_RUNTIME_BINDING_UNAVAILABLE`；有只读绑定时最多读取 SDK 中立账户会话，但因 `MARKET_TICK_CLOCK_UNAVAILABLE` 不启动策略。写入要求独立的 SDK authorization source 和有界 OperatorWriteGrant，且仍受 Feed clock 能力门禁。历史 registered-sim 记录仅供追溯，不作为当前运行保证。

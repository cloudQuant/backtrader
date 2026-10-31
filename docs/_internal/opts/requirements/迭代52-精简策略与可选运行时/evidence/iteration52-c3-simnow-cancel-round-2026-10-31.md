# 迭代 52：SimNow provider-verified 撤单轮（源码 + 实跑被前置阻断，2026-10-31）

- 仓库/分支：Backtrader `dev`，撤单源码提交 `14b234f3ce32aa27ffcecd74bcfb3f7371de3f52`。
- 证据等级：**SOURCE / FAKE（源码合同）+ PAPER_ACCOUNT 尝试（本轮为 BLOCKED，未取得账户结果）**。
- 明确不声称：本轮**没有**真实 SimNow 登录、下单或撤单发生，因此不构成 F08/F13/F20 的
  `PAPER_ACCOUNT` 撤单验收；下文所有通过都是本地 fake 合同语义。
- 未读取 `.env`、私有 `config.yaml` 内容或私密捕获正文；探测与实跑只输出固定原因码与计数。

## 1. 本轮修复的缺口

迭代 52 R3 记录的 SimNow registered-sim 撤单身份缺口：继承的 legacy 撤单路线仅按本地
pending map 派生原生 action，条目缺失或过期时退化为只带 `OrderRef` 的盲撤；交易所可忽略该
动作，而本地 Broker 已把订单标记为 `Canceled`，形成“本地终态、场内驻留”的不一致（R3 曾出现
一次真实挂单残留 `OrderStatus 3`，需由独立 000 certlib 以 `OrderSysID` 撤销到 `5`）。

交付物（`examples/unified/052_provider_demo_roundtrip/simnow_paper.py`）：

1. `SimNowPaperStoreMixin.cancel_order()` / `cancel_order_ref()` 覆盖为**先核实、后下动作**：
   以本地引用（`external_order_id`/`ctp_order_ref`/`order_ref`/`ref`）连接**恰好一条场内活跃**
   订单行，取该行的 `OrderRef` + `OrderSysID` + `FrontID` + `SessionID` 作为唯一身份。
2. 活跃集合来自带工具的 `orders_result` 查询（`attempts=2`，按 `InstrumentID`/`ExchangeID` 过滤），
   不使用本地缓存推断。
3. 身份不全或多义一律拒绝，不下原生动作：`simnow_paper_cancel_order_not_found`、
   `simnow_paper_cancel_order_ambiguous`、`simnow_paper_cancel_identity_incomplete`、
   `simnow_paper_cancel_scope_mismatch`。
4. 会话交叉检查：订单行 `FrontID`/`SessionID` 必须等于本次登录事实，否则
   `simnow_paper_cancel_session_mismatch` —— 跨会话 `OrderRef` 正是本路线绝不能转成盲撤的情形。
5. 门禁复核：撤单前后各检查一次 arm/frozen 状态（`simnow_paper_cancel_gate_closed`），
   冻结态不下动作。
6. 原生动作字段由本模块自建 `CThostFtdcInputOrderActionField`（SDK 导入仍惰性），
   `RequestID` 与 `OrderActionRef` 使用同一枚新鲜递增 id，`ActionFlag=0`；
   发送返回非零或抛异常记 `simnow_paper_cancel_send_failed`，不伪造成已受理。
7. 每次成功下动作产生一条有界收据（≤8 条）供证据投影：身份四元组、工具/场所、
   `request_id`、`submit_code`、`source=simnow_paper_verified_cancel_v1`。

## 2. FAKE 合同验收

```
cd examples/unified/052_provider_demo_roundtrip
C:/anaconda3/python.exe -m pytest -p no:asyncio tests/unit/test_iteration52_simnow_paper.py -q
→ 26 passed, 1 warning in 0.39s（一条既有 pytest 配置 warning）
```

覆盖正/负例：唯一活跃行匹配后按四元组下动作并生成收据；无匹配、多义匹配、身份字段缺失、
跨 Front/Session、非本工具/场所、门禁未 armed、已 frozen、API 方法缺失、`RequestID` 非法、
原生返回非零、发送抛异常，以及收据不泄漏凭据。这些是本地 fake 叶子合同，不证明原生
`ReqOrderAction` 语义或场内终态。

## 3. 真实撤单演练（本轮结果：BLOCKED，未触及 provider）

演练配置 `examples/unified/052_provider_demo_roundtrip/config.simnow_cancel.yaml`：
GTC 挂单偏移 `+50bps`（低于市场，意在驻留）、`cancel_after_seconds=4.0`、
`hard_timeout_seconds=60.0`、`max_orders=1`、名义上限 `25000.0`。

命令（SimNow 交易时段，13:32 北京）：

```
cd examples/unified/052_provider_demo_roundtrip
C:/anaconda3/python.exe run.py --config config.simnow_cancel.yaml --live --allow-write
```

结果摘要（脚本仅打印脱敏摘要）：

```
status=BLOCKED reason=front_selection_failed:no_front_pair_eligible venue=SIMNOW
credential_env_names=[]（未进入凭据解析）
```

证据文件：`examples/unified/052_provider_demo_roundtrip/evidence/20261031T053201Z_052_simnow_demo_roundtrip_BLOCKED.json`
（344 bytes，SHA-256 `70cf89e78abf93680fd58456eaf7b187bf8d69ca2bba84af01305f84861d7a53`）。

判读：失败发生在**前置选择**阶段，早于凭据解析、SDK 导入、原生登录与任何写请求；
因此本轮**既不是撤单路径失败，也不是账户通过**，只是场所可达性条件不满足。

## 4. 同期独立传输探测（credential-free TCP）

使用既有 operator 工具，未新建脚本：

```
C:/anaconda3/python.exe -m backtrader_runtime.cli check-ctp-fronts \
  --strategy-dir examples/unified/013_3_sa_midfreq_simnow/runtime-ctp-private
```

结果（无地址、无凭据输出）：

| 字段 | 值 |
| --- | --- |
| `status` / `reason` | `no_pair_reachable` / `no_configured_pair_reachable` |
| `configured_pair_count` | 5 |
| 每组 `md_connected_count` / `td_connected_count` | 0/3 与 0/3（五组全部） |
| `sdk_imported` / `authentication_attempted` / `credential_resolver_invoked` | false / false / false |
| `trading_writes` / `settlement_writes` | 0 / 0 |
| `selected_config_index` | null |

该探测是**当时本机**的传输观察，不建立登录、账户或写授权，也不说明前端配置错误。

## 5. 边界与下一步

1. 撤单账户验收需在 SimNow 标准前置可得的时段窗口重跑同一条命令；重跑是一次**新的**真实尝试，
   不是对已失败调用的重复。验收判据：策略 `phase=canceled`、独立查询显示
   `OrderStatus=5`（已撤终态）、账户 flat、disarm 0/0、收据四元组与查询行一致。
2. 若演练留下驻留单，按 R3 既有做法由独立 000 certlib 以 `OrderSysID` 撤销并记录，
   适配器保持 freeze，不做盲撤。
3. CTP 费用投影与部分成交/迟到回报案例（F08）仍是独立缺口，本轮不涉及。
4. F13 的“授权撤单”在源码/合同层已交付，其账户层状态在 §5-1 完成前保持未验收；
   不得以 26 项 fake 通过替代账户证据。

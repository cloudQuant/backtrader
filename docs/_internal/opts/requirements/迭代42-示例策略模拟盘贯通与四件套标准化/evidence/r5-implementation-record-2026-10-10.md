# 迭代42 R5 — 013_2（rb 跨期）实现与离线验收记录（2026-10-10）

状态：**实现与离线验收完成**；真实成交往返（rb 主力/次主力双腿 + 平仓 + 对账）待
周一 2026-10-12 SHFE 交易时段执行（建议夜盘 21:00 窗口，与 R1/R4 串行）。本记录为
该轮的实现与离线证据。

## 范围（实现轮）

- 013_2 四件套化：`README.md` + `config.yaml` + `calendar_arbitrage_strategy.py`
  （原 `strategy.py`，git mv）+ `run.py`（新标准入口，dry/`--replay`/`--live`）；
  旧 `run.py` → `legacy_runner.py`；`run_runtime.py` 同步改引 `legacy_runner`
  （登记 LOCAL_REPLAY_ONLY 路由恢复）。
- 策略迁移 = R4 同一组变更（§4 三类缺陷修复 + `close_offsets`/`deadline_clock`/
  `broker_position_mode`/`engineering_trigger` 参数），保留 013_2 的高频差异：
  `trade_logger_tick_interval=128`（报告节流）、period 60 / entry_z 1.5 /
  confirmations 1 / min_interval 0.1 / max_pairs 5 / max_holding 120s。
  与 013_1 迁移模块逐字 diff 仅剩上述高频差异（已核对）。
- 双腿同交易所（SHFE）：`run.py` 的腿部唯一性守卫由“交易所唯一”放宽为
  “合约唯一”（rb2701≠rb2705；013_1 的 m/RM 天然不同交易所，不受影响，已同步在
  013_1 中修正并复验 dry）。
- `simnow_direct.py`：013_3 同源字节副本（含 R4 双腿武装扩展），无漂移守卫已覆盖。
- 平仓 offset：rb 属 SHFE → 交易所元数据推导 `close_today`（与既有前缀启发一致，
  行为差异仅在离线默认被显式映射取代）。
- 配置：`live_contracts.symbols=auto`（rb 主力+次主力季度）、`exchanges.rb=SHFE`、
  `instrument_metadata.rb` tick=1/mult=10、`timeouts.run_seconds=1800`、
  `drill.hold_seconds=180`。冻结段保持原值（含 `run_timeout_seconds: 180`）。

## 离线验收（实际执行）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| dry | `python run.py` | exit 0；合约 rb2701/SHFE + rb2705/SHFE；5 组 front pair；仅环境变量名 |
| replay | `python run.py --replay`（profitable/loss） | 均 `LOCAL_REPLAY_PASS`（profitable=4 组配对动作） |
| 登记回放 | `bt-runtime run --strategy-dir .../013_2.../runtime` | exit 0；`admission_status=LOCAL_REPLAY_ONLY`、`hft_status=FAIL/NOT_ADMITTED`（保持既有标注） |
| 聚焦测试 | `pytest tests/unit/test_ctp_pair_examples.py` | 34 passed（EX1/EX2 双迁移锚点） |
| 同源守卫 | `test_examples_self_contained.py` + multiarm 测试 | 013_2 simnow_direct 字节同源通过；其余 3 项为既有基线（R9 处置） |
| Lint | ruff（本轮变更文件） | 通过（013_2 仅剩既有 ctp_example_support 两处 SIM112 基线） |

## 待执行：真实成交往返验收（周一）

命令（建议 21:00 北京后启动；08 分钟级预热 + 触发窗口 + 有界持有平仓）：

```text
python run.py --live --allow-write --drill --drill-side long --run-seconds 1800 \
  --drill-delay-seconds 600 --drill-window-seconds 600 --drill-warmup-bars 8
```

PASS 判据：会话归属 trades 中 rb 两腿（rb2701/rb2705）均 entry 成交且各腿
close ≥ entry；终态无持仓、无活动委托、无 UNKNOWN；`arm_history` 反映写入前
腿部切换；对账通过。HFT 延迟结论不在本迭代范围（保持 `FAIL/NOT_ADMITTED` 标注）。

## 证据层级

本记录为**离线/源码级**证据：dry、回放、登记回放、聚焦测试与同源守卫；
不构成账户、provider 或成交结论。周一 live 结果另起记录追加。

## 首跑彩排与修复（2026-10-10 凌晨，7x24）

013_2 首次真实 live 执行（命令与周一一致）：front 选择（7x24 唯一 eligible）→ 双臂
**首次真实武装**（rb2701+rb2705，`set2_7x24_4000x`，managed+proof）→ RUNNING（6789 真实
tick）→ `FAIL / no_fill_round_trip`（1951.8s 有界返回、run_error=null、终态 flat、
`session_order_refs=0`、`open_position_rows=0`）。

归因（源码+诊断）：drill 分支 `max_pairs=1`，而 warmup 未成熟期的自然 z 尝试先消耗了唯一
额度（attempts=1 / fired=false），此后 `_try_open` 永久短路 → drill 永不触发。修复与回归
见 R4 记录同节；Monday 013_2 窗口放宽为 delay 1200 / window 1200（[20,40] 分钟）。
彩排同时验证：选择/登录/查询/双臂武装/证据落盘/有界清理全链真实可用。

## 周一前四层预下单阻塞链（2026-10-10 深夜彩排逐层定位）

修复 drill 竞态后，013_2 的 7x24 彩排仍零单；连续三个约 50 分钟的有界彩排 + 订单账本
持久化（`strategy_order_ledger`）逐层定位出四个独立阻塞点（全部为本迭代已接受实现的
预置缺口，非环境问题；周一三场写 drill 若不修将全部零成交）：

1. **drill 自然路径竞态**（013_1/013_2）：`max_pairs=1` 被窗口前伪 z 消耗 → 已修复
   `1477ad469` + 回归 `4d66770cb`。（013_3 设计不同、014_1 冷历史门——审计无此竞态。）
2. **未接打标**（013_3）：`configure_live_tick_provenance` 缺失 → bar 全拒
   （`bar_schema_missing:connection_generation`）→ 已修复 `0b971a55e`（修证彩排 schema
   阻断归零；bar 全链验收留待周一标准前置）。
3. **Broker 证据门接口缺失**（四个写入口均 `require_complete_ctp_evidence=True`）：
   store 未实现 `supports_complete_ctp_queries`/`get_ctp_query_health` → 每笔订单在原生层前
   被拒 `ctp_query_capability_unavailable`。修复：`simnow_direct.RegisteredSimStore` 增加
   **忠实投影**（仅暴露真实执行的启动查询：account/positions + 参考行，含 `IsTrading`
   透传与两个计数 0），五副本字节一致；回归断言读取端所需结构（pair+multiarm 48 通过）。
4. **IOC → GFD**（013_1/013_2）：策略以 `time_in_force="IOC"` 提交，直连 CTP 第一版契约
   仅接受 GFD → 拒单码实录 `unsupported_time_in_force`（订单账本：`"CTP first-version
   orders require GFD; received IOC"`）。修复：策略新增 `time_in_force` 参数（默认 IOC，
   回放语义不变），013_1/013_2 live 入口传 GFD（014_1 未设 tif→broker 自动 GFD；
   013_3 本就 GFD——审计确认）。

### 第 5–7 层与真实成交里程碑（2026-10-10 深夜彩排序列）

- **彩排 #5（IOC 修复后）**：订单首次到达原生 SDK 层，`run_error =
  CtpExecutionGateError: ctp_execution_gate_order_insert_field_request_id_mismatch`
  —— **第 5 层**：`btapistore` 构造发单/撤单字段时从未设置 `field.RequestID = req_id`
  （dev SDK 新门要求相等）。修复：两处 builder 补设（一处修复覆盖全部写入口）。
- **彩排 #6（RequestID 修复后）——里程碑**：drill 触发 → 双腿武装切换实录
  （arm_history: RB2705 锚点 → RB2701 运行时切换）→ **两腿原生真实成交**
  （`session_order_refs=2`、`entry_by_symbol = {rb2701:1, rb2705:1}`、`trade_rows=2`）
  → 平仓腿报 `ValueError: Invalid dual-side order combination: action=sell,
  position_side=short, offset=close_today` —— **第 6 层**：`_submit` 对平仓沿用开仓
  position_side 映射（sell→short），双开双平语义应为平仓单声明"被平掉的持仓方向"。
  修复：`reduce_only` 分支反转映射（sell 平多=long、buy 平空=short）+ 策略级回归。
  该次中止留下 **2 手 7x24 残留仓位**（已取证：rb2701 多 1/rb2705 空 1，today=1）。
- **残留处置（operator 维护，有界）**：清仓脚本序列完成：定位/武装/平仓
  （rb2701 以真实成交价 3062 平今成交；rb2705 以 3097 平今成交；期间撤除挂单）→
  **终态 flat、零工作单**（v5 复核均为 0），7x24 预检条件恢复。
- **彩排 #7（平仓映射修复后）**：本次 **env 性未触发**（`engineering_trigger_fired=false`、
  attempts=0、4936 tick）——深夜 7x24 的 bar 节奏显著变慢，8-bar 就绪晚于 [20,40] 分钟窗口；
  无代码回归（抑制门在窗外也按设计不再放行自然路径）。**修复后的完整往返判定以周一
  标准前置时段为准**（#6 已证明全链可达成交层）。

订单账本持久化（`strategy_order_ledger`）是本轮四层定位的关键工具，已入 013_2 run.py。

### 后续审计：014_1 同患修复 + 策略级双开双平回归补全（2026-10-10）

- **014_1 同患确认与修复**：审计 014_1 时确认 `ctp_options_lowfreq_strategy.py` 的
  `_submit_next_leg` 只保留单一映射（sell→short），而 `_start_exit` 会把三腿方向反转后
  置 `_state="EXITING"`——与 013_1/013_2 完全同类的第 6 层缺陷（014_1 的周一写入 drill
  会走同一平仓路径，必须先行修复）。修复为按 `_state == "EXITING"` 反向映射
  （sell 平多=long、buy 平空=short），与 `exit_offset` 同步生效。
- **回归补全**：e5ec6ebc7 的提交信息曾声称"strategy-level regression"，但实际只落了
  GFD 与 store 证据两项测试。本轮补上真正的策略级回归——两个 harness 分别驱动
  013_1/013_2 与 014_1 的真实提交路径并断言
  `(side, position_side, offset)` 四元组：开仓 `buy/long/open`、`sell/short/open`；
  平仓 `sell/long/close{,_today}`、`buy/short/close{,_today}`。014_2/015 无
  `position_side`（observation tier，无写路径），审计确认无同患。
- **验证**：pair+options_lowfreq 68 通过；options tier + multiarm 109 通过；ruff 三个
  改动文件干净；014_1 仅此一份策略文件（无 vendored 副本），回放测试全绿。

### 选择器语义实证修正与 SimNow 停服窗口（2026-10-10 午后）

- **背景**：为在周一前验证平仓映射修复后的完整往返，以周一逐字命令在 7x24 发起
  013_2 彩排（session e24f94d8），干净 BLOCKED：`no_front_pair_eligible`——五个 pair
  全部 0/3（TD/MD 双端），无写入。对照探测：外网正常（baidu 443 72ms）而
  www.simnow.com.cn 超时、7x24 MD 端口 ConnectionRefused、其余 timeout →
  **SimNow 全前端主机级停服/维护窗口**（时间相关事实，非代码缺陷）。
  已置有界 watcher（`D:/temp/iter42_0132_watch_and_drill.py`，3h 上限、每分钟只探
  7x24 双端、返回即在示例目录内自动发起同一条周一 drill 命令）等待服务回归。
- **选择器语义实证修正**（覆盖 92d5a3378 的过度简化）：以伪造 `_probe_endpoint` 实证
  `select_front_pair` 真实排序键 = `_session_rank → whitelist → 延迟中位数 → 配置顺序`。
  `_session_rank` 为**会话感知**：CZCE 日盘窗口（09:00–10:15/10:30–11:30/13:30–15:00）
  内 standard 优先；窗口外（含夜盘/周末）**7x24 优先**——实证：窗口外 standard 10ms vs
  7x24 999ms 仍选 7x24；强制窗口内 11:00 则反向。该语义自 `eb3da84f3`（R1）起为
  六副本一致设计（注释即写明 "outside it the always-on engineering front is preferred"）。
  周一会话影响：步骤 1–5（日盘窗口）期望 standard；**步骤 6（21:05 夜盘）将选中 7x24**
  （#6 双腿原生成交即在该前端；§2 验收判据与前端无关，receipt 入证据）。计划两处措辞
  已同步修正。
- **前选失败细节持久化（`3e9d05d92`）**：上述 BLOCKED 复盘发现 `SimNowDirectError` 落入
  通用 handler，run.json 只留 `"SimNowDirectError: no_front_pair_eligible"`——逐 pair 探测
  样本（细节）丢失，故障归因需人工重探。六个 live 入口（013_1/013_2/013_3/014_1/014_2/015）
  统一新增专用 `except simnow_direct.SimNowDirectError` 分支，把 `reason` + `details`
  写入 summary/run.json。回归：013_1/013_2 以假 simnow_direct 模块驱动真实 `run_live`
  断言 run.json 保留裸 reason、逐 pair 拒绝原因与样本数；六入口另加源一致性守卫
  （专用分支唯一且先于通用 handler）。验证：新聚焦 8 通过；六套件 266 通过（唯一失败为
  既有环境基线 `test_receipt_rejects_critical_runtime_identity_drift`）；ruff 干净。

# 迭代42 R4 — 013_1（m/RM 跨品种）实现与离线验收记录（2026-10-10）

状态：**实现与离线验收完成**；真实成交往返（m/RM 双腿 + 平仓 + 对账）待周一
2026-10-12 DCE/CZCE 交易时段执行（与 R1 同一窗口，见下）。本记录为该轮的实现与离线证据。

## 范围（实现轮）

- 013_1 四件套化：`README.md` + `config.yaml` + `pair_arbitrage_strategy.py`
  （原 `strategy.py`，git mv）+ `run.py`（新标准入口，dry/`--replay`/`--live`）；
  旧 `run.py` → `legacy_runner.py`（冻结回放引擎；`run_runtime.py` 同步改为引用它）。
- 标准入口 = Cerebro + SDK 行情（分钟 bar + dispatch_ticks）+ 直连 registered-sim
  执行桥（`simnow_direct.py`，013_3 同源字节副本 + 双腿武装扩展）；Store/managed/
  production 写路线保持关闭（§5.1 决定不变）。
- 计划 §4 三类执行缺陷修复（登记预期行为差异，见下）：
  1. 平仓 offset：新增 `close_offsets` 策略参数（显式映射优先）+ 标准入口按交易所
     元数据推导（SHFE/INE=`close_today`，DCE/CZCE=`close`）；品种前缀启发仅保留为
     离线回放默认。
  2. 盘口缺失：`_limit()` 不再回退 close 价，返回 None；`_submit()` 拒绝下单并
     halt（`No executable book for ...`），避免盲价成交。
  3. 时钟：新增 `deadline_clock` 参数；live 传 `time.monotonic`，订单超时/持有计时
     不再依赖数据时钟；replay 默认（None）行为不变。
- 双腿武装（simnow_direct 的共享扩展，013_3 同文件同步受益）：
  一次 SDK registered-sim 准入只授权一个合约；runner 准入阶段对 m/RM 两条腿分别
  武装验证，运行期在每次真实写入之前按出站合约切换武装（先 disarm、再 arm，
  绝不写入后切换前端）；`arm_history` 值无害记录每次切换。单合约路径（013_3）
  在未配置模板时保持原行为。
- drill：一次性工程触发（`engineering_trigger` 参数，绝对 epoch 窗口）+
  `max_pairs=1` + `drill.hold_seconds` 确定性持有平仓 + 缩小 z-score 观察周期
  （`--drill-warmup-bars`）；自然信号路径不加演练。
- 顺带修复：R2/R3 改名后 012_1/012_2 的 `run_runtime.py` 仍导入旧 `run` 模块，
  已改为导入 `legacy_runner`，登记回放路由恢复（本轮一并验证，见下）。
- 测试/守卫：`tests/unit/test_ctp_pair_examples.py` 锚点更新（策略/引擎文件映射、
  新增缺陷修复聚焦测试）；`test_examples_self_contained.py` 增加
  `013_1/simnow_direct.py ← 013_3/simnow_direct.py` 字节同源守卫；
  新增 `tests/unit/test_iteration42_simnow_multiarm.py`（7 项 fake：武装幂等、
  写入前切换、dispatch 钩子、缺模板拒绝、无模板保持单武装语义、字节同源）。

## 离线验收（实际执行）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| dry | `python run.py` | exit 0；合约 m2612/DCE + RM612/CZCE；5 组 front pair；凭据仅环境变量名 |
| replay | `python run.py --replay`（profitable/loss/no_edge） | 三项均 `LOCAL_REPLAY_PASS`；profitable=4 组配对动作、loss=2 且 halted、no_edge=0 订单 |
| 登记回放 | `bt-runtime run --strategy-dir .../{013_1,012_1,012_2}/runtime` | 三项 exit 0（013_1 返回冻结配对回放；012_x 返回 `FORMULA_CHECK_PASS`） |
| 聚焦测试 | `pytest tests/unit/test_ctp_pair_examples.py` | 34 passed |
| 同源守卫 | `test_examples_self_contained.py` | 新增 simnow_direct 条目通过（其余 3 项为既有基线：000 自包含、013_x vendored 支持模块 CRLF 漂移，R9 统一处置） |
| 013_3 回归 | `test_ctp_sa_midfreq_example.py` / `admission_receipt_tool` / `pilot_supervisor` | 177+6+12 passed（1 项既有环境基线失败：`test_receipt_rejects_critical_runtime_identity_drift`） |
| 多武装 fake | `test_iteration42_simnow_multiarm.py` | 7 passed |
| 012 集成回归 | `tests/integration/test_cross_exchange_demo_contract.py` | 129 passed |
| Lint | ruff（本轮全部变更文件） | 通过（013_1 仅剩既有 ctp_example_support 两处 SIM112 基线） |

真实入口冒烟（周六非交易时段，`--live --allow-write --run-seconds 120`，无 drill →
不可能产生订单）：两次运行均正确 fail-closed 为 `BLOCKED / no_admissible_front_pair`。
当期仅 7x24 pair TCP 可达（标准前置非交易时段不可达），其合约查询缺 RM612 →
`instrument_not_found`（第二次运行起记录 `error_details`）。过程中完成：配置/环境加载、
dev SDK 严格来源校验、TCP 候选筛选、会话登录、只读预检（账户/持仓/委托/合约元数据
查询真实执行）、逐对尝试与失败记录、值无害证据落盘。未发生武装、订单、撤单或账户写入。

## 待执行：真实成交往返验收（周一）

命令（与 R1 同一窗口内串行；标准前置交易时段可达）：

```text
python run.py --live --allow-write --drill --drill-side long --run-seconds 2700 \
  --drill-delay-seconds 1200 --drill-window-seconds 1500 --drill-warmup-bars 8
```

PASS 判据（§2 成交往返 + 双腿口径）：会话归属（`_order_state`）的 trades 中，
m 与 RM 两条腿均出现 entry 成交（offset=`0`）且各腿 close 成交 ≥ entry；终态无
持仓、无活动委托、无 UNKNOWN；`arm_history` 记录写入前的腿部切换；对账（positions/
orders/trades/account 权威回读）通过。drill 兜底满足 §2 门控（一次性显式触发、
有界持有平仓）。

## 证据层级

本记录为**离线/源码级**证据：dry、回放、聚焦测试、fake 双臂测试与周六冒烟的
fail-closed 观察；不构成账户、provider 或成交结论。周一 live 结果将另起记录追加。

## 周一前修复：drill 自然路径竞态（2026-10-10，经 013_2 首跑彩排发现）

013_2 的首次真实 live 彩排（7x24，周一命令）实录：`max_pairs=1`（drill 分支）+ warmup 期
伪 z 自然尝试消耗唯一额度（attempts=1、`engineering_trigger_fired=false`、6789 tick 零开仓）。
同源代码的 013_1 具相同竞态。修复：`_try_open` 在"trigger 存在且未触发"期间抑制自然开仓
（`_natural_open_suppressed`），drill 成为唯一开仓路径；非 drill（回放/无 trigger）行为不变。
回归：`tests/unit/test_ctp_pair_examples.py` 新增 helper 参数化测试 ×2 与策略级顺序测试 ×2
（38 passed：窗口前自然信号零开仓、窗口开启即按 long 方向开双腿并标记 engineering_trigger）。
Monday 013_1 窗口放宽为 delay 1200 / window 1200。

**同类竞态审计（同轮完成，四写入口闭环）**：013_3 `purpose=engineering_smoke` 分支
drill-only（窗外一律 `engineering_trigger_not_reached`，无自然路径）✓ 无竞态；014_1 自然
z/score 门要求 `len(history) ≥ window` 根 15 分钟 bar（live 单会话不可能满足）→ drill 是
唯一可行入口 ✓ 无竞态；014_2/015 观察层无订单。仅 013_1/013_2 存在并被修复。

## 追加：013_1 7x24 彩排块 → 定位并修复真实缺陷（2026-10-10 17:25–18:0x 北京）

以周一同命令逐字在 7x24 发起 013_1 跨所 drill：运行 `live-20261010T092544Z-690c9c80`
→ BLOCKED / `no_admissible_front_pair`；失败细节持久化（`3e9d05d92`）给出
`instrument_not_found CZCE RM612`（零写入、账户未动）。

**更正（同上日晚些时候，root-owner 只读探针 + 修复）**：初步"7x24 合约清单不完整"的
环境归因**不成立**。逐合约定向清点（`D:/temp/iter42_0131_czce_inventory_probe.py`，经该例
只读登录路径，空全量查询在 7x24 不完整、定向查询全部 COMPLETE）显示：
**CZCE `RM611/701/703/705/707/709` 全部存在，仅 12 月合约缺失**（RM612/RM711）——
即 **郑商所 RM 不挂 12 月合约，`RM612` 系解析器造出的不存在合约**：
`PRODUCT_CALENDARS` 曾让 m 与 rm 共用含 12 月的月份表；当日 Nov（RM611）落在
45 天到期保护内被跳过，便回落到虚构的 RM612。**这是 013_1 的真实源码缺陷**（也解释了
此前夜间 `instrument_not_found RM612` 的全部历史记录），与前端库存无关。

- 修复 `75db53df2`：`rm` 日历改为真实 `(1,3,5,7,8,9,11)`；同日期解析从
  `m2612+RM612` 更正为 `m2612+**RM701**`（探针实证存在）；解析回归补 2026-10-10 用例、
  武装切换 harness 改用真实合约码；两测试文件 50 passed。
- 修复后以周一同命令即时重演（run id 见下）——7x24 现可承载 013_1，
  跨所双臂切换获得真实路径验证机会。
- 教训：`instrument_not_found` 先分"前端缺"还是"代码发明了不存在的合约"——
  用同前端定向查询既有月份即可区分。

## 追加：修复后重演终报 PASS（2026-10-11 11:05–11:53 北京，7x24）

周一同命令逐字重演（`--live --allow-write --drill --drill-side long --run-seconds 2700
--drill-delay-seconds 1200 --drill-window-seconds 1200 --drill-warmup-bars 8`），
运行 `live-20261011T030536Z-7e938fc7`，终报 **PASS / tier=fill_round_trip**：

- 前置选择：4 个 standard pair 非时段不可达，按会话感知规则回落 7x24（index 4，MD/TD
  各 3/3，score 94ms），`environment_switched_after_write=false`。
- 武装：双腿 `armed=true`（DCE.M2612 + CZCE.RM701，`set2_7x24_4000x`、managed、
  trading_day 20261009）；`arm_history` 实录三腿序切换 **RM701 → M2612 → RM701**
  ——跨所 disarm→arm 于写入间切换在真实路径闭环（此前唯一未实盘验证的新元素）。
- 成交：`session_order_refs=4`、两腿 `entry_by_symbol`/`close_by_symbol` 各 1、
  `trade_rows=8`；四笔 order_refs 1–4 依次为 RM701 卖开 2378.0 → m2612 买开 3408.0 →
  m2612 卖平 3411.0 → RM701 买平 2381.0（CZCE/DCE 双所，全部 completed）。
- 终态：`open_position_rows=0`、`active_orders=0`、positions RM701/m2612 均 0.0、
  `net_pnl=0.0`、`run_error=null`、2850.156s 有界结束；组合账户全程 flat。
- 意义：步骤 5 的跨所双腿往返在 7x24 真实路径已闭环（此前该元素仅有离线回归层）；
  正式判据仍为周一 13:35 标准前置六步串行。

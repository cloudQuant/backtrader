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

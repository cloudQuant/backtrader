# R5b-1：证据键分离与 SimNow 对偶族的零写观察通道（2026-10-11）

范围：`examples/unified/*`、`tests/unit/`、本轮记录。`backtrader_runtime/` 与注册表未动，
默认 `NO_WRITE / LIVE_NO_GO`、runtime 授权边界与各例写准入条件均一字未改。

## 1. `entry_tier` 与 `tier` 是两个字段（修 R5a 留下的真实缺陷）

R5a 把通道决策证据写成 `tier`，但各例 live summary 的 `tier` 早就是**结果层级**标签：
013_x `fill_round_trip|lifecycle_only`、014_2 `observation_only_feed_sealed`、
015 `observation_only_tick_arrival`，迭代 42 的证据文件按这些值判读。R5a-1 提交里
`summary["tier"] = decision_evidence` 会把这个标签覆盖掉（`py_compile` 与当轮 57 项门禁都发现不了，
因为没有任何测试执行 live 汇总路径）。

本轮把通道决策一律改名 `entry_tier`，live summary 的 `tier` 保持原语义：

- 8 个 `run.py` 的 dry/replay 报告与门 BLOCKED 载荷统一发 `entry_tier`；
- 014_2/015 的 live summary **字面量**里同时发 `entry_tier` 与 `write_grant_result`
  （从函数中段赋值上移到构造点，使 `no_admissible_front_pair` 等提前抛出路径也带证据），
  015 的中段赋值随之删除；
- 4 个 README 的真值表小节写明两字段之别；
- 新增 AST 守卫 `test_decision_evidence_never_overwrites_the_outcome_label`，
  任何把决策写进 `tier` 的下标赋值即失败。

## 2. 零写观察通道（本轮交付 2 例，2 例本已存在，4 例登记未交付）

| 示例 | live 无写授权时的行为 | 本轮 |
|---|---|---|
| `013_1` `013_2` | 新增 `run_live_observe()`：凭据解析 → 完整 MD/TD 对新鲜选择 → 原生登录 → 账户/持仓/委托/成交 + 两腿合约元数据只读查询 → `write_health` → 正常关闭；终报 `LIVE_OBSERVE_PASS`，`channel: observe` | **交付** |
| `014_2` `015` | live 通道按契约本就是观察层（`--allow-write` 在第一条语句被拒） | 只补证据接线 |
| `013_3` `014_1` `012_1` `012_2` | 仍为 `REJECTED / write_consent_missing`（`013_3` 先跑解释器守卫，`014_1` 与 `012_x` 先跑写授权判据） | **未交付，R5b-2 继续**；`013_3` 配置是迭代 22 schema、`014_1/012_x` 无 `_live_preflight`/`_instrument_metadata` 同形助手，需逐例定制 |

`main()` 的分发规则：`effective_tier == live` 时，带 `--allow-write` 走原写 drill，
不带则走 `run_live_observe`。`run_live` 内部第一条 `write_consent_missing` 判据保留，
作为直接调用时的第二道门。观察路径**从不**构造 `BtApiBroker`/`Cerebro`、**从不**调用
`registered_sim_arm`，脏账户只上报不拒跑（`account_not_clean_for_pilot` 是写 drill 的前提，不属观察）。

## 3. 验收

`tests/unit/test_iteration43_live_observation.py`（6 项，两例 × 3）在**真实加载方式**下执行：
以 `importlib` 装载该目录 `run.py`、目录进 `sys.path`、只 fake OS/provider 叶子，
`simnow_direct` 用读方法白名单 + `__getattr__` 写陷阱（触达任何 arm/submit/cancel/send 即
`WriteTouched`），并把 `backtrader.brokers.btapibroker.BtApiBroker` 换成构造即抛的哨兵。
断言的是**生命周期序列本身**：

- `start → wait_ready → stop`，且 6 次只读查询恰好是
  `account/positions/orders/trades + 两腿 instruments_result`；
- 真实 `_instrument_metadata` 用真实校验通过（fake 行携带 PriceTick/VolumeMultiple）；
- `write_health` 四项全零、`entry_tier.effective_tier == live`、`run.json` 落盘；
- 无可用对时 `BLOCKED / no_observable_front_pair` 且**一个 store 都没被创建**；
- 分发：`--live` → observe，`--live --allow-write` → drill，无 flag → 两者都不运行。

门禁对照 R0/R2 冻结基线（无新增回归）：

| 检查 | 基线 | 本轮 |
|---|---|---|
| `tests/unit/runtime` | 746 / 23 / 0 | **746 / 23 / 0**（含在 918 的合并跑里） |
| runtime + 自包含 + 012_x 集成（4+2 文件） | 未冻结 | **918 passed / 23 skipped / 3 failed**，3 项即 R0 既有红 |
| R5a+R5b 测试（3 文件） | 73+26 | **110 passed / 3 skipped / 0 failed** |
| `scripts/ci/smoke_iteration41_registered_offline.py` | 8 / 0 / 2 | **8 / 0 / 2** |
| `ruff check examples` | 176 | **176**；本轮 20 个改动文件单独 ruff 全清 |
| `refresh_cross_exchange_local_manifests.py --check` | up to date | **up to date**（键改名后已重签，本轮再次核对无漂移） |

## 4. 自伤记录

1. 013_1/013_2 的 `channel` 打标脚本对每个 `"mode": "live",` 无条件插入，与观察块自带的
   `"channel"` 撞成 F601 重复键；先回退 `run.py` 再重打，**顺带把上一段已做的
   `entry_tier` 改名一起退掉了**，直到派发测试 15 红才暴露。教训：回退一个文件必须重放
   该文件本轮全部后续编辑，且回退后要立刻跑键计数（`tier=0 entry_tier=N`）而不是等测试。
2. `entry_tier` 的注入模板漏了一个换行，两处产出 `…evidence),                "write_grant_result"…`
   同行双键 —— 语法合法、ruff 全清，只有肉眼看 diff 才发现。已按缩进捕获拆行。
3. `--dry` 与真值表脚本沿用编译通过当作验收的做法在本轮再次被证伪：三次缺陷
   （`tier` 覆盖、重复键、同行双键）都不违反语法。

## 5. 下一步

R5b-2：`013_3`（迭代 22 schema 的 SA 例）与 `014_1`（期权低频写 drill）各自补无写观察或
显式返回 `live_observation_unavailable`；`012_1/012_2` 用其 SDK 只读 preflight 组观察层。
其后 R7（复制即可运行）与 R6（索引/守卫/AGENTS）。

## 6. R5b-2 追加（同日下一轮，§2 表格的交付状态以本节为准）

§2 表把 `013_3`/`014_1`/`012_1`/`012_2` 记为“未交付，R5b-2 继续”。R5b-2 已落地，交付形态如下：

| 示例 | R5b-2 结果 |
|---|---|
| `013_3_sa_midfreq_simnow` | 新增 `run_live_observe()`：迭代 22 schema 的 `live_contract.instrument/exchange` 经 `_resolve_ref` 解析，选择完整 MD/TD 对 → 登录 → 持仓/委托/合约元数据/账户/成交只读读 → `write_health` → 关闭；不调用其整体式 `_live_preflight`（该函数把清洁账户作为写 drill 前提），故脏账户只上报 |
| `014_1_ctp_options_lowfreq` | 新增 `run_live_observe()`：保留三腿（future/call/put）与单所校验、dev-SDK 预载与解释器前置，登录后做四组只读查询并投影 `open_position_rows`/`active_order_rows`；写 drill 与 `--drill` 授权链未动 |
| `012_1`/`012_2` | 无独立无写观察路径，`live` 无授权时显式返回 `BLOCKED / live_observation_unavailable`（`write_grant_result: not_requested`），不再以 `write_consent_missing` 冒充“观察通道存在但被拒”；同一 sealed config 上的只读 preflight 属后续独立轮 |

三个 SimNow 家族例子的观察测试各自断言**生命周期序列本身**（`start → wait_ready → stop`、逐例的只读查询顺序、`write_health` 四项全零、
`BtApiBroker` 构造即抛的哨兵、store `__getattr__` 对任何 arm/submit/cancel/send/freeze/disarm 立即抛），
并各含一条分发断言（`--live` → observe，`--live --allow-write` → drill）。
既有测试与文档中没有任何一处依赖 `write_consent_missing` 这个字符串（全库 grep 为零），
因此该行为变更不产生隐藏回归。

R5b-2 门禁：迭代 43 五份测试 **118 passed / 3 skipped / 0 failed**；
`tests/unit/runtime` + 自包含 + 012_x 集成合并跑 **918 passed / 23 skipped / 3 failed（R0 既有红）**；
登记离线冒烟 **8 / 0 / 2**；`ruff check examples` 仍为 **176**，本轮改动文件单独全清；
012_x 目录清单在 run.py 再次变更后重签并 `--check` up to date（仅 `runner_sha256`/`candidate_sha256` 变化，
批准状态与 `demo_approval` 未变，新指纹不继承旧签名授权）。

至此 R5b 的“缺能力入口显式标注”要求完成：6 例中 3 例具备真实零写观察会话，2 例本为观察层并补齐证据，
1 对（012_x）以 `live_observation_unavailable` 诚实标注并给出翻转路径。

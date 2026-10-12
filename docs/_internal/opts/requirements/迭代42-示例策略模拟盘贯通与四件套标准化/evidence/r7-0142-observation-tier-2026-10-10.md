# R7 — 014_2 期权中频观察层改造与运行记录（2026-10-10）

范围：`examples/014_2_ctp_options_midfreq` 按四件套标准收敛；策略为
**决策专用**（无下单路径），按 R7/R8 计划修正案采用 **live 观察层**（零写），
`--allow-write` 明确 BLOCKED。本记录同时覆盖同轮发现的 live 入口缺陷修复
（013_x/014_x 通用）与真实环境试跑证据。

## 变更

- `run.py`：标准三模式入口。dry = 纯配置/就绪检查；`--replay` 复用冻结 FQ2 回放；
  `--live` = 观察层：真实直连 registered-sim 链（front 选择 → Store 登录/查询预检 →
  3 × BtApiFeed 分钟桶 + `closed_bar_quote_capture` → 策略 FQ2 决策），零写路线
  （不 arm、不下单）。PASS = ≥1 个完成分钟特征窗（WARMUP/ORDINARY_DECISION）且
  `feed_evidence_fault=null`、`order_write=0`。
- `config.yaml`：追加 `live_adapter`（schema 1）：真实一篮子 CZCE.SA701 /
  SA701C1080 / SA701P1080、strike 1080、multiplier 20、ticks 1.0/0.5/0.5、
  `signal.residual_floor_cny=40`（= 一个 tick 界的 20×(1.0+0.5+0.5)，显式覆盖
  回放初始值 30）、`policy.allow_write=false`、5 组 MD/TD front、
  `max_pending_decisions=8`、`quote_limit=240`。
- `legacy_runner.py`：`load_config` 剥离 `live_adapter`（回放契约键集不变）。
- `simnow_direct.py`：与 013_3 canonical 字节一致的副本（多腿 arm 协议 +
  `configure_live_tick_provenance`）；漂移守卫扩展至 013_1/013_2/014_1/014_2
  四份副本（`test_iteration42_simnow_multiarm.py` 8 条断言）。
- 测试适配：`test_ctp_options_midfreq_fq2.py` 与
  `test_ctp_options_midfreq_example.py` 在读取 config.yaml 后剥离 live-only 段
  （与回放 loader 相同契约）；入口 importlib 断言按 014_1 已验收口径收窄为
  `importlib.import_module` 禁止（`importlib.util.find_spec` 允许）。

## 同轮 live 入口缺陷修复（013_1/013_2/013_3/014_1/014_2 共性）

1. **模块级 sys.path fence**（013_3/014_1/014_2 run.py）：直跑 `python run.py`
   时先绑定 checkout 副本的 `backtrader`，不再落到已安装旧版（否则 live 导入链
   在 `BarBarrierPolicy` 处 ImportError）。
2. **解释器守卫**：live 层在写授权闸后强制 Python 3.11（本机 3.14 无法加载
   cp311 `_ctp` pyd），否则输出 BLOCKED `live_tier_requires_python_3_11`；
   dry/replay 不受限。
3. **SDK 预加载顺序**（013_3/014_1/014_2）：`_ensure_dev_sdk_path()` 先于
   `import simnow_direct`（其模块级 `_create_ctp_wrapper_class()` 会立即
   import `bt_api_ctp`，若晚于预加载会把 site-packages 旧包绑定进去，
   严格来源检查按设计 fail-closed `sdk_origin_not_dev_source`）。
4. **事件钟越界分类**（014_1/014_2 的 provider）：封存 bar 的
   `available_at` 无法映射进运行时钟域（如 7x24 环境报价钟陈旧）时，
   由裸 ValueError（→ UNKNOWN 崩溃）改为有界 `LiveRejected`：
   `BLOCKED / live_event_clock_outside_run_mapping`，details 仅含
   symbol/age 秒数/错误文本（无值输出）。

## 离线验证（全绿）

- 干跑：`python run.py`（3.14）= DRY/OBSERVATION_ONLY/exit 0；
  `--replay no_edge|edge` = LOCAL_REPLAY_PASS ×2；`--live --allow-write` = BLOCKED
  `write_tier_not_implemented_for_decision_only_strategy`；`--live`（3.14 无写授权）
  = BLOCKED `live_tier_requires_python_3_11`。
- 测试：midfreq 全组 + iteration42 组 **127 passed / 1 skipped**；lowfreq 组
  65 passed（1 例 `test_idle_sdk_command_worker_is_valid_for_store_transfer`
  为既有环境性失败：默认 python3.14 解析到旧 `bt_api_py` umbrella，非本轮引入）；
  013_1/013_2 pair 对 + component boundaries 76 passed；013_3 sa 组 177 passed
  （1 例 `test_receipt_rejects_critical_runtime_identity_drift` 为既有基线失败）；
  self-contained 组 3 失败均为既有 R9 基线项（000 + ctp_example_support CRLF 漂移）。
- Ruff 全绿（5 个 run.py + 新 simnow_direct 副本沿 canonical 字节）。

## 真实试跑（2026-10-10 04:5x 北京，7x24 环境）

命令（anaconda 3.11 + dev SDK，零写）：
`C:/anaconda3/python.exe run.py --live --run-seconds 120`

实际链路（全步骤均到达）：

1. front 选择：4 组标准前置时段外不可达；index 4（7x24）MD/TD 3/3、whitelisted、
   score≈0.4s，唯一 eligible。
2. Store 登录就绪（read_only_ready）；查询预检：account 1 行、positions 1 行、
   trading_day=20261008；三腿 metadata 与配置一致（tick 1.0/0.5/0.5、mult 20）；
   7x24 无涨跌停价（lower/upper=null，符合该环境事实）。
3. 3 × BtApiFeed 建立并真实收 tick（观测探针计数 SA701=58、C1080=26、P1080=22），
   首封分钟桶生成。
4. 结果：**BLOCKED / live_event_clock_outside_run_mapping**
   （details.available_age_seconds≈172354s，symbol=SA701C1080；exit 2，
   run_error=null）。独立探针确认 7x24 环境报价事件钟比本地钟陈旧约 47.9h
   （watermark/max_event_time 同口径），无法满足运行时钟域（该边界为设计内
   fail-closed：live 证据链要求报价钟 ≈ 接收钟）。

判定：当前小时（周末深夜，标准前置不可达、仅 7x24 可连）观察层为**证据化
BLOCKED**；翻转路径 = 交易时段经标准前置复跑（周一计划已加入 13:30 窗口行，
`python run.py --live --run-seconds 3000`）。同轮探针有一次记录性事实：7x24
环境对 SA 系列三腿均持续推送零量快照 tick（首个 tick volume=0/delta=0，为
订阅基线），随后恢复增量。

## 环境/前置事实补充（留档）

- 默认 `python`（3.14 用户站）装有旧 `bt_api_py 0.15`（D:\new_projects 来源），
  与 live 无关；live 一律 anaconda 3.11 + `_ensure_dev_sdk_path` 预加载。
- 7x24 前置可连但报价钟陈旧（非运行时刻）；标准前置仅在时段内 TCP 可达。选择器为
  **standard kind 优先、其次延迟**（本轮复核），今日标准 pair 全部不可达故落入 7x24 ——
  观察层在标准前置可达时段（周一 10:50 窗口）即可获得新鲜事件钟，无需选择器改动。

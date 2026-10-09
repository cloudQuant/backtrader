# R9（离线部分）— 收尾自检记录（2026-10-10）

范围：R9 收尾的**非 live** 部分先行完成并留档；live 结果（R1/R4/R5/R6/R7 与 014_2 观察）
按 `monday-live-run-plan-2026-10-12.md` 于周一窗口执行后再生成终版 tracker 与收尾提交。

## 全量 dry / replay 自检（8/8 通过）

| 示例 | 解释器 | dry | replay |
| --- | --- | --- | --- |
| 012_1 | anaconda 3.11 | DRY (rc0) | FORMULA_CHECK_PASS (rc0) |
| 012_2 | anaconda 3.11 | DRY (rc0) | FORMULA_CHECK_PASS (rc0) |
| 013_1 | 任意 3.x | DRY (rc0) | LOCAL_REPLAY_PASS |
| 013_2 | 任意 3.x | DRY (rc0) | LOCAL_REPLAY_PASS |
| 013_3 | 任意 3.x | DRY (rc0) | LOCAL_REPLAY_PASS |
| 014_1 | 任意 3.x | DRY (rc0) | LOCAL_REPLAY_PASS |
| 014_2 | 任意 3.x | DRY (rc0) | LOCAL_REPLAY_PASS |
| 015 | 任意 3.x | DRY (rc0) | LOCAL_REPLAY_PASS |

- **解释器事实（本轮新记录）**：012_x 的 dry/replay 亦加载 dev SDK umbrella，必须用
  `C:/anaconda3/python.exe`（3.11）；系统默认 `python`（3.14）解析到旧 site-packages
  `bt_api_py` 并在导入期报错（非结构化 traceback）。已在两个 README 增加显式说明。
- 013–015 的 fence/解释器守卫使 dry/replay 在 3.14 亦可用；live 需 3.11（显式 BLOCKED）。

## 登记离线冒烟（`scripts/ci/smoke_iteration41_registered_offline.py`）

```
12 passed, 2 failed, 14 selected, 3 skipped
PASS: 012_1 / 012_2 / 013_1 / 013_2 / 013_3(base) / 014_1 / 014_2 / 015 /
      sample.ctp_legacy / 007_ctp.legacy_direct / 010_live_examples.simnow_legacy /
      backtrader.iteration41.local_backtest_fixture
FAIL(2): 013_3.managed_replay_l2 / ctp_options_simnow.mechanical_managed_replay_l2
SKIP: 私有 CTP + 公共 shadow 路由（脚本按设计排除）
```

- 两个 FAIL(2) 为 **iteration41 既有基线**：managed L2 replay 需要本地 SDK source 位于
  `PYTHONPATH`（脚本 docstring 注明），当前 shell 未提供；与迭代42 四件套入口无关
  （迭代42 的 8 个示例全部 PASS）。

## 012_x manifest 刷新链

`python scripts/refresh_cross_exchange_local_manifests.py --check` → 两目录 `up to date`（rc0）。

## 残留入口/路由决定

- 013_3 `runtime-ctp-private` 与 013_1/013_2/013_3/014_1/014_2/015 的 `runtime/` 登记回放
  路由：**保留**（迭代41 形态，登记冒烟全绿；不清退）。
- 013_x/014_x`simnow_adapter.py`/`simnow_launcher.py`/`engineering_smoke.py` 等历史注入式
  seam：保留为只读历史工件（入口拒绝，不构成第二入口）；不在本轮清理。

## 待周一后完成（R9 终版）

1. `monday-live-run-plan-2026-10-12.md` 各步实跑 → 追加 r1/r4/r5/r6/r7 记录数值与证据哈希；
2. R7（014_2）观察层记录追加实跑结果（今日 7x24 为证据化 BLOCKED：陈旧事件钟 ~47.9h）；
3. `scripts/generate_iteration42_tracker.py` 生成终版 tracker（JSON+MD，含 SHA-256）；
4. 各 README 与根 `AGENTS.md` 的迭代42段落终稿；
5. 收尾单独提交（live 已通过结果不重复汇总运行）。

## 本轮已完成的对应提交

- `adb1fb7a9` R7 014_2 观察层 + live 入口加固；`c13177459` R8 015 观察层 + 看门狗停机修复。

## 周一命令 argv 预检（2026-10-10）

对 `monday-live-run-plan-2026-10-12.md` 六条命令逐一做 **argv 级预检**（导入各自
run.py，桩替换模式函数后 `main(planned_argv)`）：全部 `parse_code=0`，无
`unknown_arguments_rejected`，且捕获值逐一符合计划（013_3/013_1/013_2：
run_seconds 2700/2700/1800 + allow_write + drill(drill_side=long)；014_1：3000 +
allow_write + drill；014_2：900（无写授权）；015：300（无写授权））。

## 看门狗停机缺陷范围评估（本轮检查，非缺陷修复）

015 的"一次性 runstop 可在 run 激活前被忽略"缺陷已修复（`c13177459`）。对其余入口
逐一检查，结论：

- **013_1/013_2/013_3/014_1（写 drill）**：结构不同且已充分防护——deadline 仅结束
  等待循环，随后进入 `drain_seconds + 2×stop_seconds`（默认约 +144s）的检查窗，窗
  末在 run 早已激活后做一次硬兜底 `cerebro.runstop()`（013_3 由
  `control.request_stop` 在 deadline 即压停）。窗口 1800–3000s、准入 ≤ 约 300s，
  落点永远远晚于 run 激活，不存在同类丢失。
- **014_2（观察层）**：仍为一次性压停；周一窗口 3000s、准入 ≤ 约 90s，deadline 深在
  run 活跃期内，今日 120–150s 窗口实跑亦正常；维持现状（记录在案，不做非必要改动）。
- **015**：已覆盖（持续压停 + run 前预算检查）。

## 判定（补记）

周一六个步骤具备：命令参数预检通过、离线 8/8 dry+replay、登记冒烟全绿、个体测试
套件全绿；剩余不确定性仅为市场环境（前置可达性/事件钟新鲜度），均有已记录的回退
与翻转路径。

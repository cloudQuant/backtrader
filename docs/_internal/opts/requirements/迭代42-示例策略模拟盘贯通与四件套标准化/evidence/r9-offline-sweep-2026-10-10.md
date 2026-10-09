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

# 迭代42 — 周一（2026-10-12）真实验收执行计划

目的：在 SimNow 交易时段内按序执行 R1/R4/R5 的有界 drill 成交往返验收（三次独立 run，
共享同一模拟账户与同一 `C:/anaconda3/python.exe` + dev SDK `D:/bt_api_py`）。

## 时段与顺序

| 序 | 示例 | 建议窗口（北京） | 命令（示例目录内执行） |
| --- | --- | --- | --- |
| 1 | 013_3 SA | 09:00 开盘后即启动（日盘 09:00–11:30） | `python run.py --live --allow-write --drill --drill-side long --run-seconds 2700 --drill-delay-seconds 1200 --drill-window-seconds 1500 --drill-warmup-bars 8` |
| 2 | 013_1 m/RM | 13:35 启动（午后盘 13:30–15:00；m/RM 日盘） | `python run.py --live --allow-write --drill --drill-side long --run-seconds 2700 --drill-delay-seconds 600 --drill-window-seconds 900 --drill-warmup-bars 8` |
| 3 | 013_2 rb | 21:05 启动（夜盘 21:00–23:00） | `python run.py --live --allow-write --drill --drill-side long --run-seconds 1800 --drill-delay-seconds 600 --drill-window-seconds 600 --drill-warmup-bars 8` |

- 每次 run 结束（含 drain）后再启动下一个；同一账户串行。
- 标准前置仅交易时段 TCP 可达；选择器会先 7x24 后 standard（时段外）。若首轮
  admission 结果异常，记录 attempts 再决定人工干预。
- SimNow 标准前置在成交回报上可能缺少 `OnRspOrderInsert`：以场内侧订单查询为受理判定
  （R1 备忘录已有该事实）；`_order_state`/订单事件链正常时无需干预。

## PASS 判据（§2 成交往返）

- 013_3：`filled_entry>0 且 filled_close>=filled_entry`、终态 flat、无活动单、无 UNKNOWN。
- 013_1/013_2：会话归属 trades 中**每条腿** entry>0 且各腿 close>=entry（`entry_by_symbol`/
  `close_by_symbol`）、终态 flat、无活动单、无 UNKNOWN；`arm_history` 反映写入前腿部切换
  （013_1 应出现 m↔RM 切换；013_2 为 rb2701↔rb2705）。
- 证据：各目录 `evidence/live-*/run.json`（git-ignored）；随后把脱敏摘要 + SHA-256 归档到
  迭代42 evidence 目录，并在 `r1-live-run-progress` 备忘补记数值。

## 失败处理

- `no_admissible_front_pair` → 记录 attempts（含 error_details），确认标准前置可达后重试一次；
  仍失败则当日按证据化 BLOCKED 记录并说明。
- 腿成交不齐（partial_round_trip）→ 不重跑覆盖；保留证据，人工核对残余敞口（run.py 已冻结
  gate 不会继续写）。
- 任何 UNKNOWN → 停止后续 run，先对账（README/§2 层级）。

## 收尾（当日）

1. 更新三个示例的验收记录（r1/r4/r5 记录追加实跑数值与证据哈希）。
2. 生成迭代42 最终 tracker（JSON+MD，§7.1 字段：dry/replay/live/tier/trigger/env_scope/orders/
   cleanup/evidence_sha256/commit/status）。
3. 收尾轮提交（R9）：tracker + 基线清单 + 最终 AGENTS/README 校订。

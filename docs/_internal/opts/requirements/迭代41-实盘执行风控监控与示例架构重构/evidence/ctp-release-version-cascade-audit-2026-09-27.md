# CTP 合流制品版本级联只读审计（2026-09-27）

裁决：`VERSION_CASCADE_PLAN_ONLY / NO_RELEASE / NO_WRITE / LIVE_NO_GO`。

R3r3+V21 合流源码仍标 Execution `0.2.0`，与多个不同源码的旧 wheel 同名；先前 `0.2.1` 仅是 R3r3 单独迁移探针，不包含 V21、parent 撤单控制/发行器或 risk 终态解除。审计建议**预留而未分配** Execution `0.2.2`、risk `0.1.1`、parent `0.15.7`；CTP SDK 版本待最终来源/摘要冲突消解后决定。没有修改默认 pin、构建或安装最终制品。

审计列出六类剩余发行阻断：V22 G5 尚未冻结；主仓缺终态撤单证明接线；parent 控制端与证明发行器是分离快照；risk 新源码仍持旧版本；CTP 同版本不同摘要冲突；统一 wheel、RECORD/来源和合并假消费尚未通过。其主仓目标文件清单有 14 项。先前 `0.2.1`/`0.15.6` 探针主仓仍是 `77 passed / 16 failed / 1 skipped`，不能冒称统一发行。

root 复核修正后的审计 Markdown SHA-256 `f3dc0ab31cca14fcef728c699c93a179ac240a633ee1df96dd334eee97c97151` 与 JSON SHA-256 `52a4daaf8f08e4832235337c88723a47a23439591f736b0ae4dfd5fbda2a91e1`，JSON 可解析。[原始归档](ctp-release-version-cascade-audit-2026-09-27.raw.zip)保存两份文件，ZIP 完整性通过，归档 SHA-256 `81911eb5361992bd5a16bba95637bcd74bb065cb7ce42c56cf93abef2368916c`。这份审计是实施顺序和 pin 清单，不是发行或真实交易验收。

# parent 撤单控制端 r2 独立复核（2026-09-27）

裁决：`LOCAL_FAKE_RELEASE_REPLAY_PASS / FIRST_RELEASE_REJECTED / NO_WRITE / LIVE_NO_GO`。

r2 在持久 `RELEASED` 重放时，以 SQLite `mode=ro` 精确读回已准备的 monitor outbox 事件，再处理 typed dispatch resolution，最后才尝试清除 `cancel-release-in-progress` 风险锁。删除或损坏 outbox 行时会重新置位未知结果锁和释放进行中锁，审计命令回到待处理，不把本地不确定性报成成功。

独立 QA 核对冻结 manifest SHA-256 `b52e918a07195847b4011d1f68b476486ab4fb17e6dcff8e49eaaabe1babae3d`，其 1,013 个 payload 文件的大小/摘要、四项输入制品、三项关键文件及作者测试日志均匹配；在候选树外复跑 `23 passed`，再次核验候选树未漂移。root 又核对三项关键源码/测试、作者日志和独立 QA 回执，并将 13 项关键证据封存于[原始归档](ctp-parent-cancel-control-r2-independent-review-2026-09-27.raw.zip)；ZIP 完整性/内部摘要通过，归档 SHA-256 `3f1aadf5810fb1d0b44db68172f19fea004ed6683f681e0d6b2973f1dccbb307`。完整 1,013 项文件由独立 QA 对隔离冻结树核验；归档仅保存 manifest 与关键文件，并非完整源码镜像。

此项只证明本地 fake/offline 顺序与删除/损坏负测。首次 release 的外部注入授权回调没有在此证明；monitor 和 risk 分属不同 SQLite 数据库，未建立跨库原子性或防并发外部篡改。主仓五文件原有三项失败仍须用 r2 整合候选复跑，不能据此开放默认 CTP 撤单路由。

后续首次释放审计明确推翻了将 r2 当作完整释放合同的可能：授权回调推进时钟后缺到期重检，首次 append 后删行缺事件读回，且人工构造的 CTP execution scope 可通过假 authority 范围检查。[r3 作者候选](ctp-parent-cancel-control-r3-author-candidate-2026-09-27.md)在隔离源码中补了局部门槛，正接受独立 QA 和主仓合流；r2 的重放复核结果仍只对原重放用例成立。

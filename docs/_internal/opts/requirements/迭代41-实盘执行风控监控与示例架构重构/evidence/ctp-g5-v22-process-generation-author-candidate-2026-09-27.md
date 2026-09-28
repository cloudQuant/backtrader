# G5 V22 进程代次恢复源码候选（2026-09-27）

裁决：`AUTHOR_SOURCE_ONLY_SLICE_PASS / G5_BLOCKED / NO_WRITE / LIVE_NO_GO`。

V22 候选基于已独立审阅的 R3r3+V21 合流 manifest `00577665667a33c9a7d62d331c0cad99b0b660790d0b475d0bd8c1b6caa6e2dd`，改动 7 项源码/测试。账本新增持久进程代次及 schema 20/21→22 迁移，模型中的一次性进程退出证明把精确 CLAIMED 集合原子补记 `UNKNOWN` 并 poison 账户 owner；旧无进程代次的 CLAIMED 保持不可重派、不可新 owner。首次全包诊断因新建空库被 V21 预检当成旧 schema 而有 20 项失败；只对真正无 schema 对象的空库修复后，作者聚焦 `188 passed / 2 skipped`、全包 `309 passed / 2 skipped`，Ruff 与 `py_compile` 通过。初次失败仅保存结构化摘要，没有原始 stdout，不能写成完整原始日志已归档。

root 核对候选 manifest SHA-256 `8244038ab975f30de6c0ba56c140f033ddd5b5ce5fb3cabc9e60abb7bf24066d`、基线 manifest、7 项 delta 与 7 项验证制品大小/摘要。[作者原始归档](ctp-g5-v22-process-generation-author-candidate-2026-09-27.raw.zip)共 17 项文件，ZIP 完整性及内部摘要通过，SHA-256 `b191d7cb8cfddb7547c071678e8d48e197e60c928143c2810d02861ad5dfd640`。独立源码与严格隔离 wheel 消费 QA 另行进行，当前不把作者结果当最终验收。

该候选仍标 `bt_api_execution 0.2.0`，没有唯一发行 wheel。进程退出 verifier 默认 `None`，仓库没有受信 Windows Job/进程句柄验证器、服务身份或 pin；私有 Python 能力对象不能阻止不可信同进程策略伪造注入。假 verifier 测试只验证本地 Store 事务与拒绝语义，不证明真实 OS 进程已退出，也不授权任何 CTP provider、模拟盘或实盘写入。

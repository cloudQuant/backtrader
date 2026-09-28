# G5 V22 进程代次恢复源码独立 QA（2026-09-27）

裁决：`SOURCE_QA_PASS_G5_BLOCKED / NO_WRITE`。独立 QA 验证冻结 V22 manifest SHA-256 `8244038ab975f30de6c0ba56c140f033ddd5b5ce5fb3cabc9e60abb7bf24066d` 与 R3r3+V21 合流基线 `00577665667a33c9a7d62d331c0cad99b0b660790d0b475d0bd8c1b6caa6e2dd`；隔离副本 39/39 个源码/测试项在运行前后均与声明摘要匹配。

独立源码焦点 `240 passed / 2 skipped`，完整包 `313 passed / 2 skipped`，新增事务原子性边界用例 `4 passed`，Ruff 与 py_compile 通过。两项跳过的桥接用例依赖真实 Trader/原生 SDK 路径；QA 阻止了该导入。V20 非空 `CLAIMED`/inflight 记录迁移到 schema 22 后为 `UNKNOWN`、无退出证明、不可取得继任 owner；其旧 callback/family owner 行仍为 `ACTIVE`，故不能把它记作统一 POISONED。V21 旧无代次 `CLAIMED` 迁移为 `UNKNOWN` 且 callback/family owner 为 `POISONED`。注入在命令 UNKNOWN、callback poison、family poison 和证明记录插入处的失败均回滚；成功提交后精确记录、poison、审计一致，重开也不允许重派或证明重放。

初始作者诊断的 `287 passed / 20 failed / 2 skipped` 是空 SQLite 文件误入 V21 预检造成；当时未保存原始 stdout 或源码哈希，只保留结构化失败摘要。修复后的精确冻结候选由独立 QA 重验空库创建/重开与完整包，不把初始失败记录写成具备完整原始证据。

独立回执 SHA-256 `8f5c21ced6f97496f451ac5823094995bc09a919640077b91406420c3c29e264`，测试后完整性回执 SHA-256 `a215bbb73b0f5af9fab9b40db10774f8dd05171ab8b465432074034b0b65e2a4`。root 复核回执声明的 39 项隔离源码及 24 项 QA 制品，并将 68 项文件封存到[原始归档](ctp-g5-v22-independent-source-qa-2026-09-27.raw.zip)；ZIP 完整性与内部摘要通过，SHA-256 `6420754178a895c81bb0e44d9d8b21c4e7ce6ccc22b8b6e9d10ff8e1e2d1d3bb`。

候选仍是 `0.2.0` 源码，进程退出由注入假验证器声明，尚无与真实 Windows native-owner worker/Job 绑定的受信服务证明。它没有 provider、网络、账户或原生 CTP 操作，不能作为模拟盘或实盘写入验收。

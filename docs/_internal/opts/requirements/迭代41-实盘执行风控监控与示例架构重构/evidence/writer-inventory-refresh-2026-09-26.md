# Writer 静态清单刷新

2026-09-26 本轮扫描：287 个文件、221 个 writer AST 候选、49 个动态执行候选、0 个解析错误。270 个候选均有处置记录，仍全部为 `REVIEW_REQUIRED / NOT_AVAILABLE`。

本次按稳定 candidate ID 合并：保留 258 个现存记录的审核字段，更新其中 25 个位置；加入 12 个资源释放候选；删除 1 个已更名的旧 `ConfigActionLease.close` 候选。删除的完整记录保留在[增量回执](writer-inventory-refresh-2026-09-26.json)，没有覆盖或丢弃其历史处置。

新增位置包括 `ctp_simnow_signed_review.py` 的 SQLite/OS handle 释放、`ctp_f14_signed_receipt_contract.py` 的 connection close，以及 `ctp_config_action_linearization.py` 中更名后的 close。它们没有因静态语法命中而被认定为真实报单入口，也没有被自动授予交易权限。

两个 collector/verifier 测试文件通过 **9 passed / 6.04s**；[JUnit](writer-inventory-refresh-2026-09-26.junit.xml)保留在此。验证只证明清单覆盖当前 AST 候选，不证明外部 writer 排除、运行时零 I/O 或 live 准入。后续源码改动需再核对增量。

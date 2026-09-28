# I22 stable runtime-ID migration — independent QA archive

This archive preserves both revisions and their independent evidence. R1 is `PARTIAL / NEEDS_REVISION`: its replacement same-node test no longer executes `_sdk_order_request` or asserts zero binding lookups, zero reservations, and unchanged `order.info`; a separate QA-only probe verified the behavior, but does not restore candidate coverage. R2 is `PASS` for the narrow local fake contract: it restores the actual-method negative assertion and independently reproduces the patch output hashes.

R2 focus: one guarded node passed; SDK/native import attempts, network attempts, and loaded SDK/native modules were zero. No private config, real provider, order, or account was accessed. R2 is not broad I22 acceptance and does not establish an external Actor, provider authority, G6-P, or production readiness.

Raw author and QA trees are retained in the four `*.raw.zip` files. `ARCHIVE-INDEX.json` hashes every raw member and copied reference file. The r1 packet is historical and is not superseded as evidence; r2 supersedes its candidate disposition only.

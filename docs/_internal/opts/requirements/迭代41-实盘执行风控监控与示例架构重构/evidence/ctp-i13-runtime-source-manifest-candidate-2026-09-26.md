# I13 运行时源码清单候选（2026-09-26）

状态：`DIRTY_TREE_CANDIDATE / PIN_UNSET / NO_PROVIDER_RUN`。

`scripts/ctp_i13_source_manifest_candidate.py` 从当前工作树构造父启动器要求的 canonical schema-1 清单。输出只在 `artifacts/ctp_i13_source_manifest.current_dirty_tree_candidate.json`，含 91 个 `backtrader_runtime/**/*.py` 路径及其 SHA-256；排除两个 code-owned pin 文件。候选文件 SHA-256 为 `c1152f3e6c7d38090a68dfc397f6a8853932b2abe7acd7c39175b403d0d3039a`，10,557 bytes。它只存源码路径与哈希，不存私有配置、账号、密码或前置地址。

离线审计确认该清单的路径集精确等于当前 runtime Python inventory 减去两个 pin；所有条目的哈希与当时的 raw source bytes 相符，重建字节相同。父 launcher 与 runtime identity parser 均接受该 *格式*。初版脚本的输出路径约束不够严格；随后增加固定 `artifacts` 目标、父目录 reparse 拒绝及路径篡改负测。当前定向测试 8 passed，Ruff、`py_compile` 和 Python 3.8 AST 语法解析通过；这只证明离线候选生成合同。

父启动器的离线 seam 另补充了 seal 返回值的 `source_root` 和有序 `stdlib_paths` 与预检 plan 的绑定检查；任一不符，在 finder 安装和 metadata Job setup 前关闭 seal 并拒绝。负测覆盖不同源码根、标准库路径，以及关闭方法缺失或失败时明确报告 `source_seal_cleanup_failed`。父启动器、sealed importer 与清单生成器三组测试由主代理独立复跑为 `42 passed, 1 existing PytestConfigWarning`，Ruff 通过。这仍是注入式 fake 验证：父启动器没有受审的外部 descriptor 来源、真实 Windows Job 接线或可用源码锚点。

该工作树有大量未提交代码，候选不是 commit-bound manifest；任何 `backtrader_runtime` Python 内容或 inventory 改动都会使它过期。受信路径 `backtrader_runtime/ctp_i13_source_manifest.json` 仍不存在，I13 代码 pin 仍为全零，父启动器据此 fail closed；I15 manifest 也不存在，I15 pin 仍为空。清单 schema 不包含独立 SDK 的 I13 源码、wheel、`_ctp.pyd` 或 DLL，也没有外部 review descriptor/anchor 或真实 TD/MD 观察。不得把此 artifact 复制成受信清单、设置非零 pin 或用它复用已消耗的一次性 marker；G1～G4 与默认 `NO_WRITE / LIVE_NO_GO` 状态不变。

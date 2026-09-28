# AC41-63 静态 writer 候选扫描范围扩展

日期：2026-09-27。此记录冻结本地静态候选扫描增强；不构成 AC41-63 的 writer-closure、运行时可达性或路由授权验收。

## 变更与当前结果

默认 collector 保留原 Iteration 41 运行时扫描范围，并递归扫描 `examples/` 中除生成输出与私有 runtime state 外的 Python 源文件，以及仓库根目录全部 `.py` 脚本。新增受控路径基线 `scripts/iteration41_writer_inventory_scope.json`：182 项，包括 180 个普通 `examples/` 子目录与 2 个根脚本。新增目录/根脚本没有受审基线分类时显式输出 `UNCLASSIFIED`，并标记 `REVIEW_REQUIRED`；默认仓库合同测试要求基线完整，因此未分类路径会使该测试失败。显式 `--include` 仍可用于局部扫描，输出 `CUSTOM_SCOPE_NOT_CLASSIFIED`。

机器生成路径另行标记：27 个 `__pycache__`、`examples/logs` 和私有 CTP runtime state 摘要项。私有 state 仅显示固定目录摘要，不枚举或扫描子项。路径标签只表示扫描覆盖，不表示 writer 安全或关闭。

| 静态输出 | 改前快照 | 改后快照 |
| --- | ---: | ---: |
| Python 文件扫描 | 287 | 349 |
| writer 候选 | 221 | 327 |
| dynamic 候选 | 49 | 62 |
| 解析错误 | 0 | 0 |
| 静态候选处置记录 | 270 | 389 |
| 路径覆盖状态 | 未提供 | `BASELINE_CLASSIFIED`，211 项已分类，0 项 `UNCLASSIFIED` |

389 个处置项仍全部是 `REVIEW_REQUIRED / NOT_AVAILABLE`。处置表中的 `UNRESOLVED_POTENTIAL_LIVE_WRITE` / `live_route_count` 是尚未解决候选的标签/计数，不是可用 live route 的证据。collector 只读取源码并用 Python AST 分类；不导入或运行 provider、策略、SDK 或 runtime。扫描范围/AST 命中均不证明完整 writer closure。

JSON 的 `source_root` 保留字段但固定写为相对标记 `.`，不记录运行机器绝对路径。生成的候选、处置、基线和差异 JSON 经检查不含绝对路径、受保护 config、`.env` 或凭据内容。此检查针对本次 AC41-63 文件，不是对 evidence 目录中历史 JSON 的全仓隐私审计。

## 验证

聚焦测试命令：

```text
python -m pytest -p no:asyncio tests/unit/scripts/test_collect_iteration41_writer_inventory.py tests/unit/scripts/test_verify_iteration41_writer_dispositions.py -vv --tb=short
```

结果：12 passed，1 个既有 `PytestConfigWarning`（当前 pytest 不识别 `asyncio_default_fixture_loop_scope`），18.68s。Ruff 命令 `python -m ruff check scripts/collect_iteration41_writer_inventory.py tests/unit/scripts/test_collect_iteration41_writer_inventory.py`：通过。

本机 `py` launcher 没有 CPython 3.8；collector 与新增测试通过 CPython 3.11 的 `ast.parse(feature_version=(3, 8))` 语法兼容检查。此项不是在 CPython 3.8 上执行测试。

CLI 的最终静态汇总：`CANDIDATE_DISCOVERY_ONLY`、`BASELINE_CLASSIFIED`、349 files、327 writer、62 dynamic、0 parse errors、0 unclassified paths。处置刷新结果：`GENERATED_REVIEW_REQUIRED`，389/389 项保留 review-required 状态。完整聚焦日志见 [verification.log](verification.log)。计数变更摘要见 [inventory-output-diff.json](inventory-output-diff.json)，冻结的路径基线副本见 [writer-inventory-surface-baseline.json](writer-inventory-surface-baseline.json)。

## 改前与改后 SHA-256

“改前”SHA 指编辑前逐字节快照；两份原始未跟踪 Python 文件和原始 inventory/disposition JSON 的字节副本保留在本机临时备份中。原始候选 JSON 含机器特定 `source_root`，因此仅保留其哈希、不复制进 canonical evidence。文件字节数与哈希如下：

| 文件 | 改前 SHA-256 | 改后 SHA-256 |
| --- | --- | --- |
| `scripts/collect_iteration41_writer_inventory.py` | `B74F5E133E0965EC89E4F32238FCD452D1FC1046450C8BED0504EE4808D07ADA` | `54AF45DE1C4D14AAF1C3849C9B820F505EDB7A4C34C344B8E4157F490C9E0ED5` |
| `tests/unit/scripts/test_collect_iteration41_writer_inventory.py` | `5A411DA56DA5A006C4A7501F9BD45EF2EC3CA9DBDB7C613B9B762870843EA0BA` | `C133E3DF976E572EBE2D1017497D10549A0DF7398A88F1B0FFD25E8E80C5ED6E` |
| `live-execution-inventory-candidates.json` | `841585B4C393323EF2101D854D928AA75A1150524C2ECFEB8F5D79FCE10F50A6` | `FACBBC93067D77A317E3A0ABDE5EF89BC77BD53E4A4EB18722B51124E3E20780` |
| `live-execution-writer-dispositions.json` | `05B9A7A8E95DA6E7B44B1084FF9B38EF6D146F208ADDAFE1A4ED4D75D83F074D` | `95116E8866A50D645664764856F1CEB6E855B3D05E540F7E38D59F30EA65C7FD` |
| `ctp-current-acceptance-matrix.md` | `B67853123CBDD7932EA53551C616F227B2D47C6CEADDEB2CA7C2AC1B474957EB` | `47BC6E33C5DCDF29D7103D86E49248975AAE20F18B306DC6385EFC05D461E08A` |
| `AGENTS.md` at the start of its scope-note edit | `CAFA49D7CF30DE8EBC9358038143ACAC9DA4DD5D253B90E694494C3CB9ED331D` | `9BBE5D75F4D1F4DD90C9CEA62F94556AAD546918191E2C37A05E244D577D2F89` |

新建路径基线 SHA-256：`C473B4390D70477978C0EB9673E267244D78A57D0ACB2E8DF6D5F7D3BFA60DD7`。本证据目录中的输出差异 SHA-256：`D38F9D5CD6DE7F61D0937AC3C4C711116B7F0EB7439F5C3E1816A5A4F69495B1`；验证日志 SHA-256：`B702A631C4E3B425D3E5C9DB47AAB9F4B7F9F726B4758848A9B1F375C061E3B5`。完整冻结文件哈希另见 `SHA256SUMS.txt`。

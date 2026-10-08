# OKX M01 root-helper lifecycle integration R1

This packet integrates the already reviewed R2 root-helper lifecycle transform into the fixed M01 source chain. It updates exactly three of the 19 public runtime source pins: `current_reader.py` receives the exact R2 transform, `entry.py` pins that reader, and `cases/M01/run.py` pins the updated entry. The other 16 map rows retain their preceding R2 bytes.

## Public source pins

- Reader: 68,215 bytes, SHA-256 `5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc`.
- Entry: 5,952 bytes, SHA-256 `e0613b66fa54d5ea155da263d1e901e8ada78adf7d83a7e1c8dc5430ea440d1e`.
- M01 runner: 1,992 bytes, SHA-256 `d498e32fcb573781a3eec25eff4c7ba98bfe2c8d4d94f9e5a9b078ab4074641e`.
- `source-map.json`: 2,877 bytes; its compact canonical body is 2,876 bytes with SHA-256 `2647a75e29a0ae54c09d5f5c3626a377a50e6d2d8dac38f76162660fe76979ba`; the physical LF-terminated file SHA-256 is `07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3`.
- `source.zip`: 151736 bytes, SHA-256 `337d8f48eed1de8e7f880d6c8a24cf41e3707649cd0b0c3be87cc0b0948d39b3`, with 26 indexed public source/test members.
- `source-index.json`: 9970 bytes, SHA-256 `8cd0360bb9519daf785412a6176091d2ca0ff4471e2bf65aba011aeec3444564`.

The prior R2 selected-source map (`db7b…`) and source index/archive remain unchanged. The R2 transform source is `scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py`, SHA-256 `c53833b20238cb82d491bf7972508a604e56c8ad3158cada7060f9910629a78e`; its sourcefake test is pinned in the source index. The lifecycle gate R7 and source-close reconciler R7 are included as unchanged support inputs. Their historical files are not edited.

## Historical sourcefake fixture

The additive test reads the old public R2 `source.zip` only as an immutable historical fixture (archive SHA-256 `fb319aa4b066a839dc8681d2ac30897374bece35d90bf29d6c26b28c40b7ee35`). It confirms that the archived 63,711-byte `b350…` reader still binds under the frozen source-close R7 verifier, then runs one exact transformed reader through the R7 lifecycle gate and fake V2 supervisor leaves. The relocated temporary imports are test fixtures; they do not prove runtime origin or deployment admission.

## QA and limits

The focused Windows sourcefake command passed 16 tests with one existing warning: pytest configuration sets `asyncio_default_fixture_loop_scope`, which is unknown in this environment when the asyncio plugin is disabled. Black (`--target-version py311`), Ruff, and `py_compile` passed for the added test and selected sources. See `qa-command.txt` and `source-qa-result.json`.

This packet is public source and fake-leaf evidence only. It does not update or read the fixed protected deployment documents, does not establish the Root source-admission/release preflight, and does not establish a fresh M01 actual gate, provider/account read, Job cleanup acceptance, or formal M01 PASS. Root must use the reviewed fixed-metadata rebind helper with its held old-document bytes, verify this exact 19-row map and review identity, preserve the prior documents, then perform the separately reviewed admission/release preflight and one authorized formal M01 demo read.

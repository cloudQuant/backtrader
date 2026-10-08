# M01 Root helper lifecycle gate R7 independent review

Decision: `GO_SOURCE_FAKE_ONLY / ACTUAL_ROOT_BLOCKED`.

## Reviewed bytes

- Gate: `scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r7.py`, 75,271 bytes, SHA-256 `43e2b3cee8da9f1ebcf148992160512893615bfa15fc118ced491b04dd05ac72`.
- Test: `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r7.py`, 27,576 bytes, SHA-256 `73fd436e5de9327f0d02f59baab66b60b1887bf1bf0d27ceeaca7a5c018b3038`.

The focused fixture binds the R2 transform `scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py` (`c53833b20238cb82d491bf7972508a604e56c8ad3158cada7060f9910629a78e`) and these source bytes:

- Transformed reader: `5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc`.
- Supervisor: `188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82`.
- Worker: `aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41`.
- Current types: `cd896051b0580195baa569989622c18fec594afc3772e7ea4af9e4cf226778ea`.
- Contract: `1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db`.

The test also imports the public R2 fake-leaf fixture at `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py` (20,224 bytes, SHA-256 `d6df3de0af5695d6842c711597dddd998dc3f394144be89d720c851e1c600848`). R7's `_ISOLATED_INPUTS` map does not pin that imported fixture itself; this review independently read back its hash. It is test-only and supplies synthetic Win32 leaves. No native, provider, private-input, or actual Root execution was performed.

## Findings and checks

R7 closes the R6 property descriptor gap. It derives each declared property accessor slot (`fget`, `fset`, `fdel`) from the exact source AST, requires the runtime property to have the same slot set, and checks every accessor against its pinned source code. The added foreign-setter regression rejects a property that retains its pinned getter but adds an undeclared setter. The existing property-to-function, classmethod-to-function, foreign-globals, dataclass code/default mutation, exact source closure, and retained-context checks remain in the focused suite.

Independent isolated QA used CPython 3.11.5 at `C:\anaconda3\python.exe`, with `-I -B`, plugin autoload disabled, `PYTHONPATH` removed, `-c NUL`, `-p no:asyncio`, `-p no:cacheprovider`, a fresh repository basetemp `.codex-tmp/m01-r7-independent-20261009-a`, and the exact R7 test path. Result: 23 passed in 6.85 seconds, exit 0, no warnings.

## Root composition condition

The gate does not independently validate arbitrary computed module globals that were changed before gate entry. For example, it checks source-derived literal assignments, but a compiled regular expression such as `worker._HEX64` is a computed value. R7's module docstring makes this an explicit caller precondition. Any actual Root packet must show that Root:

1. Fresh-loads all five modules from the exact held bytes above inside its audited invocation.
2. Before calling this gate or running any worker/native/provider or other untrusted code, captures the complete module, class, function, and global state for those modules.
3. Verifies that captured state after the gate call and retains the exact module/source context if cleanup or verification is uncertain.
4. Uses the production pinned `_hold_runtime_files`; the test's fake holder is sourcefake-only.

That outer baseline is a composition requirement, not something proven by this R7 sourcefake suite. Until Root supplies the corresponding source-bound loader and pre/post baseline evidence, this review does not grant an actual Root gate or credential-free local execution result. No account, provider, native, or M01 acceptance follows from these tests.

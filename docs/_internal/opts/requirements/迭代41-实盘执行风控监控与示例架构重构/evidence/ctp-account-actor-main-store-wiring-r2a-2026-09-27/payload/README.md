# CTP Store AccountActorPort wiring candidate r2a

**Status: `AUTHOR_CANDIDATE / NO_WRITE`.** This isolated delta is based on frozen R2 and does not alter the main Store or default route.

R2a closes the environment-read timing gap: explicitly selected CTP routes are rejected before reading either route environment variable. Nested explicit CTP is found using a snapshot of only reviewed scalar and exact built-in dictionary routing facts; opaque custom objects, API/client objects, actor/context objects, and credentials are not inspected. Environment-dependent ambiguous routes remain fail-closed before local client/resolver/adapter work.

See [r2a QA report](evidence/qa-report.md), [two-file patch](r2a-apply.patch), [patch replay log](evidence/r2a-patch-replay.txt), and [verification commands](evidence/r2a-verification-commands.txt). The frozen R2 manifest/source/test/patch/JUnit lineage is preserved in `evidence/r2-parent/` and `input-sources/r2/`.

Focused checks: 4 explicit/environment adversarial cases, 18 boundary cases, and 25 adapter/live-guard cases passed. The legacy 30-test CTP Store comparison remains 9 passed / 21 fail-closed policy failures. Ruff and `py_compile` passed. No actor authority or route was enabled.

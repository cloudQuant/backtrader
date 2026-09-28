# Iteration 41 G5 OrderRef / ActionRef author candidate

**Classification:** author candidate only. **Independent QA:** pending; assigned
separately to `simnow_settlement`. This archive is not an acceptance record.

## Scope and guard state

This archive packages the isolated G5 OrderRef/ActionRef candidate from
`D:\temp\iteration41-g5-order-authority-20260927-candidate`, including the
frozen source inputs, implementation copy, proposed Backtrader bridge patch,
test output manifests, and original test/tool logs. The frozen candidate was
not modified during archival.

Status remains `LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`. No production
source, default registry, CLI, protected configuration, credentials, or
network/provider state was changed or included. Store managed submit/cancel
remain fail-closed.

## Archive contents

The raw ZIP contains the frozen input tree and SHA-256 manifest; output
manifest; SDK authority candidate; Store-facing fake/offline bridge; proposed
`ctp_i9_parent_request_builder.py` patch and applied-copy verification; source
README; all candidate tests; and all test, Ruff, compile, patch, and failure
logs. The sidecar JSON index lists every ZIP member, byte length, and SHA-256.
The `.sha256` sidecars cover the ZIP and index file.

The preserved offline results are 14 candidate tests passed, 27 frozen SDK
focus tests passed, and 54 Backtrader focus tests passed with 47 skipped and
one existing pytest configuration warning. The normal pytest-asyncio
collection error and the initial wrong-PYTHONPATH collection error are
retained alongside corrected reruns. Ruff, Python compilation, and patch
application checks passed.

## G5 blocker

The reviewed BtApiStore managed `_sdk_order_request` path still rejects before
the legacy parent OrderRef allocation call. The inspected SDK snapshot has a
durable OrderRef reservation, but no durable ActionRef table/API or native
ActionRef callback correlator; its MaxOrderRef/legacy seed is caller supplied.
The proposed builder patch requires a worker extension
`stage_prepared_dispatch(..., action_identity=...)` and exact persisted
readback. The current worker does not implement that argument, so this
candidate is hard-blocked before dispatch. No Store route or runtime
registration was changed.

Trusted native MaxOrderRef and legacy ActionRef evidence, clean SDK producer
pin, shared account-wide writer fencing, UNKNOWN/restart reconciliation, and
native/account lifecycle acceptance remain unresolved. This author archive
does not claim provider acceptance or deployment readiness.

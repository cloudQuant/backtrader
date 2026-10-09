# OKX M01 V3 protected metadata rebind R2 source candidate

Status: public source candidate, awaiting independent review. The fake-OS tests were authored but not run in this preparation task. No protected metadata, private configuration, native API, provider, account, or process was accessed.

## Candidate files

- Helper: `scripts/iteration41_okx_m01_v3_protected_rebind_r2.py`, 28,418 bytes, SHA-256 `0baa2191b8d5b99b42e7a13ddc217f0d90291db8279b20f74a3d92c676649810`.
- Focused fake-OS tests: `tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r2.py`, 23,557 bytes, SHA-256 `4268d340cae45dbcf7574c38f98f2546df78f9a7ff82049f0baecad2904b5eea`. The fake tests were authored but not run in this preparation task.

The candidate is unregistered. It does not edit the canonical reader, current source map, prior R1 helper/test, or any protected file.

## Current source binding

The helper requires the exact current 19-row source map, physical SHA-256 `07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3` (2,877 bytes), plus the integration R1 independent-review note and its test:

- Review note: 3,820 bytes, SHA-256 `c09eb8be009567b70d50a063e042ef7d75af8ce8d2368fd568bdb4b82e38263b`.
- Reviewed integration test: 9,809 bytes, SHA-256 `21d43a5e8d1c517c2ffaa147c96f58343fb188432d4fae47717a5b68b6ec040d`.
- The transformed current reader is 68,215 bytes, SHA-256 `5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc`. Entry and fixed runner pins are checked in the helper as well.

The source-review reference remains `iteration41-okx-m01-source-owned-v3-review-r2` because that is the reader’s fixed admission identity. The helper compiles the exact pinned reader source and checks the code/global bindings and defaults for `_require` and its four metadata-validation functions. Fake-OS regressions verify that replacing `_sha` or `_require` with same-globals functions carrying different code, or mutating a required reader constant, is rejected before any protected-OS leaf is called. It also requires the current integration review digest, reviewed test digest, and current map pins; the unchanged reference alone does not authorize the changed map.

## Metadata generation and fail-closed behavior

The previously accepted deployment was rebound to the public map digest `db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3`; its `r2-20261009-preservation` backup generation was consumed. This candidate validates that R2 admission/reference pair and targets the reviewed current map above. It uses only the fixed new backup child `r3-20261009-preservation`, checks that child is unused, preserves old admission/map bytes in new owner-only backup files, updates source-map first and deployment last, and verifies same-handle readback and held identities/ACLs.

The focused fake suite covers successful current-map binding while preserving a synthetic consumed R2 backup, rejection of the occupied R3 child, current-review identity rejection before OS access, reader and `_require` source-binding regressions, exact old R2 map/reference checks, and a source-map write failure that leaves the old admission and preserved backup bytes intact while retaining uncertain handles. The fake suite does not establish real ACLs, Win32 behavior, account readiness, or M01 acceptance.

## Root call contract

A future Root call must hold this exact helper module as well as the 19 current public source files, current source-map bytes, review note, reviewed integration-test bytes, exact reader module and code/global bindings, and the verified CUv2 private module for the entire call. Root must verify the fixed parent ancestry, current old R2 metadata state, and absence of the fixed R3 backup child before invoking with `io=None`. It must retain its host, source leases, compiled modules, helper-retained handle context, and call context whenever the helper returns an uncertain failure. The helper returns only finite status/error categories and booleans; it never returns protected bytes or hashes.

This candidate does not authorize or perform Root invocation, admission release, account/provider access, or a formal M01 result.

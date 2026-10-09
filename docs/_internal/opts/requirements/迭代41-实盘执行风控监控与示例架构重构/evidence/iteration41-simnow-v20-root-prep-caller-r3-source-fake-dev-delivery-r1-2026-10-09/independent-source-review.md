# SimNow V20 preparation caller R3 independent public-source review

**Decision: `GO_SOURCE_FAKE_POSTCHECK_REPAIR_ONLY`.** This review covers the frozen public caller and its focused sourcefake fixture only. It does not authorize another actual preparation call, host close, credential-free Gate, activation, or C01 acceptance.

## Reviewed pins

- Caller: `.codex-tmp/simnow_v20_root_preparation_actual_caller_r3_20261009.py` — 25,011 bytes, SHA-256 `12e7009e6e6e794c377bd9811701596929bdfb86676509bc6bd10ab4c0ba4dda`.
- Fixture: `.codex-tmp/simnow_v20_root_preparation_actual_caller_r3_test_20261009.py` — 16,923 bytes, SHA-256 `66f9e03c61493fe211c1533f7b3ded5131dd986e10630bb5932ccbba1f5e23f7`.

## Findings

At caller lines 436–455, R3 treats the precheck and lease-held public source maps as separate reads: each value must be exactly `bytes`, within the 2 MiB cap, equal in length and content, and independently hash to its pinned digest. It retains the authoritative identity requirement `host.source_bytes[path] is lease.held_source_bytes[path]`, plus exact source-module and `sys.modules` alias identities and the host/lease source-object identity. The 26-row maps and source snapshots remain validated before the per-row checks. This removes the false precheck-read-versus-held-read object identity requirement without relaxing held-source binding.

The fixture exercises `prepare_once` through the pinned R6 preparation entry with a synthetic canonical `contextlib.contextmanager` CUv2 source hold. It constructs a fresh bytes object for every held public row; the successful path asserts distinct precheck/held objects, equal content, matching digest, and host-to-held object identity for all rows. It then rejects a modified held row and a replaced public module alias, checks the fixed `RootPreparationCallerError` codes (`entered_precheck_binding_invalid` and `public_source_binding_invalid` respectively), restores fixture state, and confirms the original postcheck passes again. This covers the reported two-read false rejection and a genuine alias failure.

`prepare_once` marks preparation exceptions and re-raises them unchanged (lines 579–593). The code invokes only the preparation entry, verifies Gate/activation state remains unused, and does not close the retained host or lease. The fixture installs public-file, import, native, network, and process guards before loading the candidate modules. The author reports the focused fixture passed 1/1; this review did not run it.

## Limits

The consumed R2 host 1497, its original `public_source_binding_invalid` exception, and its result remain historical and untouched. This sourcefake review does not establish a successful real preparation, resolve that host's custody, or establish Gate/C01/account acceptance. No tests, Git operations, host operations, private or external-software reads, or live/provider actions were performed for this review.

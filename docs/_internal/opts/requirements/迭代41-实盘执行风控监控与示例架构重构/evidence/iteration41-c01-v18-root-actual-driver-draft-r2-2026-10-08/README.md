# SimNow C01 V18 Root actual-driver draft R2

Status: source-only Root driver draft. It has not been independently reviewed or run against an account, provider, native SDK, Windows API, or live process. Official C01 PASS remains **0**.

## R1 actual-entry regression

The public R1 Root diagnostic is copied under `reference/r1-parent-diagnostic/` and hash-pinned. Root's R1 call blocked before invoking the wrapper because the driver expected 29 public source rows while CUv2 yielded 31 held rows: those 29 sources plus the pinned Python executable and DLL. Root verified all 31 held hashes and physical pins, then the original CUv2 manager exited normally, completed postverification, matched physical pins again, and released all retained references. The host session exited 0. No account, provider, or native stage started, and official C01 PASS remained 0.

## Fixed activation path

The driver requires a pinned final independent source-fake review, a matching Root readback, the packet self-pin, the exact V18 wrapper pin, and the R1 diagnostic pin before it loads CUv2 or invokes the wrapper. It verifies the complete 29-row V18 public source closure and its on-disk copies. It constructs a normalized held-pin map from those 29 rows and the two pinned software paths, rejects any normalized public/software overlap, then requires CUv2's held map to match all 31 keys and hashes exactly. Public and software counts remain separately reported as 29 and 2.

The wrapper is loaded from bytes in that same held map and called with its fixed activation CLI:

```text
--activate-c01-v18-td-read --expected-wrapper-sha256 a77627312d0823284ebe8d673392668abf31e8fd6fc2a91892d4a215be004075
```

The wrapper chooses its own fresh admission ID and owns the bounded Windows Job and child pipes. The driver captures wrapper stdout and stderr in memory, accepts only the exact 22-key finite projection, and never reads the protected receipt or private captures.

## Failure cleanup and delayed result

If a complete held map is valid and an error occurs before wrapper entry, the driver makes one normal `__exit__(None, None, None)` call and verifies CUv2 post-close and physical pins. It never calls `__exit__` when `__enter__` did not return or after an exit was already started. Invalid or changed held maps, wrapper-started failures, and uncertain cleanup retain the current scope and references. A PASS is returned only after the wrapper reports every Job/EOF/handle/thread cleanup field true, its same-call unresolved-Job list is empty, the full held map still matches, the CUv2 scope exits, and post-close pins pass.

The driver result is a Root profile result, not official C01 acceptance. It records `official_c01_pass_count: 0` and `formal_c01_pass: false`; an actual result would still require the separate acceptance process.

## Fake-only checks

The focused tests exercise a fake CUv2 map with 29 public sources plus the two software rows, path-case/slash normalization, and the exact 31-row union. They also cover software tamper, missing and extra software rows, normalized overlap rejection, clean pre-wrapper cleanup, unentered and already-closed managers, uncertain wrapper cleanup, the exact outer argv, the synthetic seven-value source tuple, and optimized-Python rejection. No actual activation, provider, native SDK, WinAPI, or production child-process operation was run.

The frozen V18 wrapper packet is copied under `reference/v18-activation/`; its complete 29-source activation closure is copied under `source/`. The wrapper packet's source-fake review and test results do not review or authorize this separate driver draft.

## Root pre-activation contract

The final Root readback must bind this driver's SHA-256 and packet-pins SHA-256, the independent-review hash, V18 activation packet pins, wrapper and entry pins, CUv2 pin, the R1 diagnostic hash, 29/29 public source hashes, 2/2 software hashes, and 31/31 complete held-map entries. It must record `driver_executed: false`, `private_inputs_read: false`, `actual_root_provider_native_acceptance: "NOT_RUN"`, and `official_c01_pass_count: 0`. The independent review binds the same driver, packet pins, R1 diagnostic, and counts with verdict `GO_SOURCE_FAKE_ONLY`. Example contracts are under `reference/`. The driver refuses activation without both exact artifacts.

No R2 actual activation command has been run. No private config, `.env`, captures, provider, SDK/native origin, or WinAPI path was accessed while preparing this packet. The only `D:/temp` access for this work is the prescribed source-QA interpreter and its QA environment during fake-only testing.

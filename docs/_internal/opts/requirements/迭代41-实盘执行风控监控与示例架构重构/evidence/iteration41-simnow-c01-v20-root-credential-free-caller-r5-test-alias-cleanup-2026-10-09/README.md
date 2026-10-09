# V20 Root preparation composition R5

Status: `SOURCE_FAKE_ONLY / EXECUTION_NOT_RUN`.

R5 preserves the bounded-precheck R2, caller R2, and preparation R4 artifacts.
The R3 static review found that the preparation code compared the driver's
`os.path.normcase(os.path.normpath(root))` value to an unnormalized
`Path.resolve()` string. R4 applies the same normalization to the repository,
the pinned driver's `_source_root_for_driver()` result, and the entered lease
root. It also registers the exact precheck-loaded driver module at the fixed
alias before the existing identity check.

## Source-fake scope

The focused composition test runs the real R4 preparation function and real
bounded precheck. It compiles all 26 pinned public modules from their exact
held public bytes, then exercises the pinned driver's actual typed lease
entry, source binder, `_outer_lease_current`, and precheck
`validate_precheck_against_entered_lease` functions. It verifies that the
driver alias resolves to the exact precheck-loaded module and that the normal
source snapshots match.

The CUv2 boundary is synthetic. The test supplies a generated in-memory
context manager and synthetic software hashes, and adjusts the test-loaded
driver's CUv2 constants/object snapshot to those synthetic values. It does not
read the CUv2 file or any software payload. The synthetic generator yields
the already verified public bytes and returns normally only during test
cleanup. The test does not exercise real CUv2 file locking/postverify, run the
credential-free gate, invoke the C01 wrapper, launch a process, create a pipe,
or call WinAPI, native, provider, SDK, or network code. It does not establish
formal C01 PASS.

The test removes only aliases and host entries it created. In particular, it
resolves the driver alias from the host's explicit driver module reference;
the production host's source map is keyed by source path rather than alias.
The R4 independent static review confirmed the 26-row map and preparation
flow. Its only note was a test cleanup fallback that could remove a preexisting
CUv2 CLI alias if preparation failed before a host was retained. R5 makes the
fallback restore or remove the alias only when the current binding is the
exact CUv2 module created by this test. A focused regression verifies that a
preexisting alias survives both the no-created-module and test-module cases.

R5 changes only the source-fake test and evidence metadata. The preparation
source and its 26 public source pins are unchanged from R4.

## Frozen references

- Bounded precheck R2 packet pins: `references/r2-precheck-artifact-pins.json`
  (SHA-256 `ccd9a6cbdb2187a4d6b7a82f856e4c0ff44c2a316f2983f98d45fcb9fbfdf43d`).
- Caller R2 packet pins: `references/r2-caller-artifact-pins.json`
  (SHA-256 `704d34e8abc5f318790fb7b076189441b0ad7c9b39d582dbe0e822aca0767036`).
- The exact 26-public-row/3-software-metadata manifest is copied to
  `references/runtime-source-pins.json` (SHA-256
  `e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387`).
- R3 independent static review is preserved as historical HOLD at
  `iteration41-simnow-c01-v20-root-credential-free-caller-r3-driver-registration-independent-static-review-r1-2026-10-09/README.md`
  (SHA-256 `4ee1bbfdd7ea3a17a46b4c4d3e752f709a5270cb3d50a573b193c551781e19e9`).
- R4 independent static review is at
  `iteration41-simnow-c01-v20-root-credential-free-caller-r4-independent-static-review-r1-2026-10-09/README.md`
  (SHA-256 `7dca9fe82d4394b366f61998339626c6b1ce214712a77a7e9b58cd1e6617cc66`);
  its sole note is addressed by the R5 test-only cleanup.
- The R2 caller static HOLD remains preserved at
  `iteration41-simnow-c01-v20-root-credential-free-caller-r2-bounded-precheck-independent-static-review-r1-2026-10-09/README.md`
  (SHA-256 `4da8f3dd84ef0aca44588f0520b05a7abab990e4a41bb07610c30300bcc1fc00`).

## Focused QA

From the repository root:

```powershell
python -B -m pytest -q "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09/test_root_gate_host_preparation_source_fake.py" -p no:asyncio --tb=short
python -m ruff check "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09/prepare_root_gate_host.py" "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09/test_root_gate_host_preparation_source_fake.py"
```

Result: `12 passed`, with one existing pytest configuration warning. Ruff
reported all checks passed on the preparation source and source-fake test. No
real software payload, private input, environment value, CUv2 lease, process,
pipe, WinAPI, native, provider, SDK, network, actual gate, or Git operation ran.
Official C01 PASS remains zero.

`artifact-pins.json` binds the eight public source, test, reference, and QA
files in this packet. It intentionally does not hash itself.

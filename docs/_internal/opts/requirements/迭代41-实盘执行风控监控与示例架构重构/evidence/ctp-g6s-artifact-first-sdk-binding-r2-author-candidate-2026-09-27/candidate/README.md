# G6-S SDK artifact binding R1 custody attempt

Status: `ISOLATED_SOURCE_FAKE_ONLY / NO_ACCEPTANCE`. This R1 is a new isolated
candidate at `D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927-r1`.
It is based on the preserved R0 manifest
`bbf863557deb20dcadf766fcb98eeabca97922c0cc72e543f5468e59fce480c4`.
The main repository, default route, default artifact policy, SDK candidate, and
R0 evidence were not modified.

## What R1 proves locally

On Windows, the candidate opens retained handles for the RECORD, every
manifested SDK member, and relevant path ancestors without write/delete share
access. It validates file identity, digest, reparse status, and ACLs, then reads
Python source bytes from the retained handles and compiles those exact bytes
through a private importer. The fake NTFS tests show that replacement/rename
of an already retained source is blocked until the handle closes, that a race
which replaces a source before custody is rejected before the marker module is
loaded, and that an unlisted SDK package module is rejected before execution.
The importer rejects changes to `sys.path`, `sys.meta_path`, `sys.path_hooks`,
`sys.path_importer_cache`, or an already-loaded SDK `sys.modules` entry before
cached evidence is used.

The fake tests use no SDK binaries. The test that creates a file beneath a
retained directory also records the limit: a directory handle alone does not
prevent a new child from being created. The candidate therefore uses a fixed
manifest module map instead of claiming directory-handle custody proves an
exact package inventory by itself.

## Remaining blockers

- `_CODE_OWNED_ARTIFACT_POLICY` remains `None`; no SDK artifact can pass the
  public pre-client gate. No code-owned release pin, approved wheel, signature,
  or externally anchored source-manifest digest is available.
- `_ctp` is only statically checked in tests. Its loader remains CPython's
  path-based `ExtensionFileLoader`; no native extension was loaded, and this
  candidate does not demonstrate a handle-bound OS image load or prove the
  loaded image through an independent Windows process boundary.
- Import-hook snapshots and module identity checks are in-process controls.
  They detect the tested mutations, but Python globals, `sys.modules`, and
  import machinery are not an isolation boundary against hostile concurrent
  code in the same process.
- This slice does not establish a complete, independently trusted dependency
  closure for every external import, an immutable installed environment, or a
  signed deployment ACL/source root. The rejected `D:\temp` tree is not used
  as a trusted SDK installation.

Consequently this remains `NO_G4 / NO_G6-S`; the real route stays fail-closed.
No SDK/native module was imported or executed; no credentials, private config,
provider, or network were accessed.

## R1 verification

The exact fake-only focus, fresh JUnit result, Ruff results, and source manifest
are under `evidence/r1-custody-attempt/`. The focus includes SDK artifact
binding, Windows custody, and TD settlement readiness tests. Ruff check and
format check pass for the four changed Python source/test files. This is local
Windows evidence only; it is not a wheel, release, deployment, or G1/G4/G6-S
acceptance result.

## R2 loader identity follow-up

R2 is an isolated source/fake candidate derived from the frozen R1 archive
SHA-256 `d5aa16bec66c7618f58b1039f87c7a774ec9958a848cbd29a94e7527887e84f0`
and R1 manifest SHA-256
`4cda34fadd2c73efb999a0411657eb625b30caa2adce5a0e56ef7527a90f8080`.
It does not alter the main checkout, default route, or unset artifact pin.

R2 captures the exact CPython importlib/machinery objects and loader method
descriptors used by the gate. Every cached-artifact check compares those
identities, the fixed module spec/loader/origin, and the installed module
identity before the extension delegate can run. An adversarial fake test
replaces `ExtensionFileLoader` after the gate; another replaces it from the
retained `.pyd` read hook after digest verification. Both reject before the
replacement constructor or `exec_module` runs. Additional cases mutate
`ModuleSpec`, `module_from_spec`, and `PathFinder.find_spec` after the gate.

Focused fake-only result: 52 passed, 0 skipped. Ruff check, Ruff format check,
and in-memory `compile()` passed for the two changed Python files. A fresh
process import guard confirmed the candidate module origins, unset code-owned
policy, and zero `bt_api_ctp` modules loaded.

This still does not prove handle-bound native loading. In the installed
CPython 3.11.5 source, `ExtensionFileLoader` is constructed with `(name, path)`
and delegates to `_imp.create_dynamic(spec)` / `_imp.exec_dynamic(module)`;
there is no retained file-handle parameter. The fake tests do not load `_ctp`.
Retained Windows handles block replacement in the tested case, but Python
same-process checks cannot isolate hostile code. No approved installed wheel,
release identity, external pin, or deployment trust root exists. Status remains
`AUTHOR_CANDIDATE / NO_G4 / NO_G6-S`; production readiness remains closed.

Detailed R2 source delta, focused logs, static-check logs, and CPython loader
source excerpt are stored under `evidence/r2-loader-identity/`.

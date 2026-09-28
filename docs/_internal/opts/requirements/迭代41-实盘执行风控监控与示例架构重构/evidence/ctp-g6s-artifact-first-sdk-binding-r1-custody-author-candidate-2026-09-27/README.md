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

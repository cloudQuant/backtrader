# External SDK release-readiness audit — 2026-09-15

> **Historical pre-publication snapshot.** This audit retains the original candidate, permission, version, and blocker observations. It is superseded for current release status by [the joint acceptance record](../../1.4.0联合验收与发布记录.md) and [the post-fix local closeout](post-fix-local-closeout.md): bt_api_base 0.15.4, bt_api_ctp 2.0.2, and bt_api_py 0.15.3 are published. Do not read the pre-publication tables below as current remote state.

> **Main-repository branch boundary correction:** this document records only
> separate SDK repositories. For Backtrader itself, the permitted promotion is
> `dev` → `development`; `master` is an historical read-only baseline and is
> **NOT_TOUCHED**. SDK tables mentioning their own `master` branches do not
> authorize or imply any Backtrader master operation.

## Scope and method

This is a read-only audit of the local `bt_api_py` superproject and its
`bt_api_base` and `bt_api_ctp` submodules.  No checkout, reset, merge, fetch,
commit, push, build, upload, tag, release, or secret value read was performed.
Remote branch and tag values were queried with `git ls-remote`; package
versions were queried from the official PyPI JSON endpoint.  GitHub secret
*names* were queried only to establish whether a workflow has its declared
credential available.

## Candidate topology and merge readiness

| Repository | Public target | Candidate | Relationship | Candidate range | Result |
| --- | --- | --- | --- | --- | --- |
| `cloudQuant/bt_api_py` | `dev` `40deb51b8855cdd2e0120067a1c988ab3a9068e2`; `master` `2be8dbc25b0f49f4734ad337fcd7abe53840c3b9` | `ee3a8bc1385fcb5a06196638566560a696f7c304` | Both public targets are ancestors | 4 commits from `dev`, 20,530 additions / 1,442 deletions | Fast-forward to either target; use `ee3a8bc1`, not later unrelated `b22a6785` |
| `cloudQuant/bt_api_base` | `master` `6db0c19329dc94528de697e65166c0b15dfd2565` | `74be52d8432c348c93304e9f3b5774bb4dbc766c` | `master` is an ancestor | 3 commits, 2,320 additions / 203 deletions | Fast-forward; merge-tree had no conflict markers |
| `cloudQuant/bt_api_ctp` | `master` `ac0bc8196a2262c66138631725f02a5ab00c3de9` | `b371098d5f7f91c8843da1ff6ded6da568ac8f4e` | `master` is an ancestor | 5 commits, 18,067 additions / 1,186 deletions | Fast-forward; merge-tree had no conflict markers |

The three candidates are already exposed locally as
`codex/release-backtrader-1.4.0-sdk`, but none of those branch names is
published remotely.  The candidates are mutually aligned: `ee3a8bc1` moves the
superproject gitlinks to `74be52d8` (`bt_api_base`) and `b371098d`
(`bt_api_ctp`).

`bt_api_base` and `bt_api_ctp` have no public `dev` branch at all.  To satisfy
the requested `dev` and `master` update, create `dev` at the tested release
commit and fast-forward `master` to the same commit.  Their current CI triggers
cover `main` and `master`, not `dev`, so a `dev` push alone does not run CI.

Use the remote `bt_api_base/master` SHA above.  The local `master` checkout is
stale (`e63d20f`), while its `origin/master` tracking ref matches the current
remote `6db0c19`.

## Version and tag decision

| Distribution | Current PyPI latest | Current candidate metadata | Existing release tag state | Recommended new release |
| --- | --- | --- | --- | --- |
| `bt_api_base` | `0.15.3` | `0.15.3` | `v0.15.3` exists | bump metadata to `0.15.4`, tag `v0.15.4` |
| `bt_api_ctp` | `2.0.0` | `2.0.0` | GitHub release/tag `v2.0.1` exists, but its peeled commit still declares `2.0.0` | bump metadata to `2.0.2`, tag `v2.0.2` |
| `bt_api_py` | `0.15.0` | `0.15.3` | only `v0.15.0` exists | retain metadata `0.15.3`, tag `v0.15.3` |

`bt_api_ctp` must not reuse or move `v2.0.1`: that tag already points to
`a8a3792995ebee73a3d54860d56a5af2520bbf5f`, whose `pyproject.toml` says
`2.0.0`.  Although PyPI never received `2.0.1`, `2.0.2` is the first new,
unambiguous release identifier that preserves the published Git history.

The dependency ranges admit the proposed order: `bt_api_ctp` requires
`bt_api_base>=0.15,<1.0`, and `bt_api_py` requires `bt_api_base>=0.15.2`.
Publish `bt_api_base 0.15.4`, then `bt_api_ctp 2.0.2`, then `bt_api_py 0.15.3`.
The final Backtrader SDK CI pins should use those exact PyPI versions rather
than unpublished Git SHAs.

## Governance and CI facts

All three repositories are public, unarchived, and the authenticated account
has admin/push permission.  Each has zero rulesets and its checked branch
protection endpoint returns HTTP 404, so no required reviewer or required
check is currently enforced remotely.

* `bt_api_py` defaults to `dev`; its test workflow covers `dev` and `master`.
  Its release workflow is the safest of the three: TestPyPI manual dispatch
  requires a supplied SHA that exactly matches the checkout and is reachable
  from `master`; production publishing is allowed only for
  `release.published`, checks master reachability, and requires tag/version
  equality.  It uses PyPI trusted publishing (`id-token: write`), not its
  repository `PYPI_API_TOKEN`.  Only a `github-pages` environment currently
  exists; PyPI trusted-publisher registration cannot be verified without
  PyPI-side authority.
* `bt_api_base` defaults to `master`; `ci.yml` covers `main` and `master` only.
  It runs Ruff, format, tests on Linux/macOS/Windows and Python 3.9–3.14, and
  builds/checks artifacts.  Its MyPy step is non-blocking (`|| true`).  Its
  `publish.yml` uses repository secret `PYPI_API_TOKEN`, which exists by name.
  The workflow's `testpypi` manual option is ineffective: it builds but has no
  TestPyPI upload step.  Its tag-conditioned publish job in `ci.yml` is also
  unreachable because that workflow is not triggered for tags.
* `bt_api_ctp` defaults to `master`; `ci.yml` covers `main`, `master`, and
  `v*` tags.  It runs the same source quality/test matrix and builds artifacts.
  `publish.yml` builds an sdist plus cibuildwheel artifacts for Linux x86_64,
  macOS x86_64/arm64, and Windows AMD64, and runs a native-import smoke command
  for each wheel.  Production uses existing repository secret
  `PYPI_API_TOKEN`.  Its TestPyPI path requires `TEST_PYPI_TOKEN`, which was
  not present in the repository secret-name list.

## Release verification commands

Run all Python commands through the required Anaconda base interpreter.  The
following are the repository workflows expressed as local commands; execute
them from the stated repository after the version-bump commit.

```bash
# bt_api_base
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pip install -e '.[dev]'
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest tests -v --tb=short -q
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff check src/
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff format --check src/
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base mypy src/ --ignore-missing-imports
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m build
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m twine check dist/*

# bt_api_ctp (local host-native build; CI also requires the cibuildwheel matrix)
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pip install -e .
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest tests -v --tb=short
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff check src/
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff format --check src/
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base mypy src/ --ignore-missing-imports
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m build

# bt_api_py
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pip install -e '.[dev,security]'
SKIP_LIVE_TESTS=true /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest tests -v \
  -m 'not network and not integration and not performance and not e2e and not ctp' \
  --cov=bt_api_py --cov-fail-under=40
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff check bt_api_py tests
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base ruff format --check bt_api_py tests
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base mypy bt_api_py tests --ignore-missing-imports
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m build
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m twine check dist/*
```

After each PyPI upload is visible, use a fresh virtual environment outside all
three source trees and install exact versions in release order.  The final
minimum smoke gate is:

```bash
python -m pip install 'bt_api_base==0.15.4' 'bt_api_ctp==2.0.2' 'bt_api_py==0.15.3'
python -c "from bt_api_py import CtpExecutionApprovalCapability; import bt_api_ctp"
```

This confirms the symbol whose absence blocked Backtrader's public-SDK test
collection.  It does not certify live CTP/SimNow activity.

## Release blockers and order of operations

1. Make the three version/tag corrections above on the aligned candidate
   commits, then run local tests/builds and the remote CI on `master`.
2. Publish `bt_api_base` first.  Its existing token-backed production workflow
   can be manually dispatched, but it cannot currently rehearse TestPyPI.
3. Publish `bt_api_ctp` second.  Its wheel matrix must complete before PyPI
   publication; TestPyPI is blocked until a `TEST_PYPI_TOKEN` is configured.
4. Publish `bt_api_py` last through its protected release flow.  If its OIDC
   trusted publisher is not configured at PyPI, the production job will fail;
   that configuration is not observable from the repository and must be
   established without exposing a token.
5. Verify exact PyPI installs, replace Backtrader's Git archive SDK pins with
   the released immutable versions, and rerun the full Backtrader SDK job.

# SimNow paired-front selection: accepted dev round

## Scope

Repository: `D:/source_code/backtrader`; branch: `dev`.
Parent commit: `857d5531bbbb1e188dfab7d27737eb61e346e281`.

This round contains exactly the following five source/test paths, their five explicit checkout line-ending rules in `.gitattributes`, and this record:

- `backtrader_runtime/ctp_front_pair_probe.py`
- `scripts/ctp_000_paired_front_selector.py`
- `tests/unit/runtime/test_ctp_front_pair_probe.py`
- `tests/unit/scripts/test_ctp_000_paired_front_selector.py`
- `tests/unit/scripts/test_ctp_000_paired_front_selector_independent.py`

One to eight complete configured MD/TD pairs are accepted. An endpoint is reachable if at least one bounded sample succeeds. A pair is eligible only if both of its own endpoints are reachable; endpoints from different pairs are never mixed. All pairs failing raises a typed failure. Eligible pairs rank by the larger of the MD/TD successful-sample median latencies, then configured order. Stability and failed-sample counts do not outrank latency. A single pair is supported.

## Acceptance

On 2026-10-08, the three listed test files passed **64 tests** in 0.96 seconds, with one existing pytest configuration warning. The designated source-QA interpreter used `-I -S -B -X utf8`, explicit repository/approved-site-package paths, plugin autoload disabled, `-p no:asyncio`, `-p no:cacheprovider`, and a fresh repository `.codex-tmp` basetemp. Tests exercise single/multiple pairs, one success per side, all-down and one-sided failure, whole-pair identity, latency ranking, bounded deadlines, malformed evidence and socket cleanup using inert boundaries.

The existing independent public ranking review dated 2026-10-07 verified this selection rule. Historical Root TCP observations are separate transport evidence; this commit does not reclassify those observations as account evidence. Current native read profiles use the corrected pinned selection source, but SimNow C01 is still BLOCKED at funds snapshot construction.

Acceptance level: **source/offline selection contract**, not provider login, trading, or certification PASS. This round grants no execution authority. Account-suite acceptance remains 12 PASS / 3 BLOCKED / 84 NOT_RUN; optional combinations remain 0/16.

## Delivery

The accepted source/test files are staged explicitly. Unrelated working-tree changes, private configuration, account captures, and subsequent funds/Root admission candidates are outside this commit. No extra worktree was created. The commit hash is the Git commit containing this record; the post-commit delivery ledger records that hash separately.

The repository has `core.autocrlf=true`, while the accepted selector and its new tests currently have LF and the existing runtime probe/test have CRLF. Explicit per-file `eol` rules preserve these reviewed working bytes on future checkouts; they prevent Git's default line-ending conversion from invalidating raw source pins. The staged blobs are verified after applying Git's checkout filters to match the accepted working bytes.

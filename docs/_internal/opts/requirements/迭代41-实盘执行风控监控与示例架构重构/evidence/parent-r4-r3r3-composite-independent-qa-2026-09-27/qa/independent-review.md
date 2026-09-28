# Independent QA: parent R4 + execution R3r3 composite

Status: ACCEPTED_WITH_LIMITS_FOR_FAKE_LOCAL_CONTRACT_ONLY

## Frozen inputs and integrity

Candidate: D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1
Composite source manifest SHA-256: 751717a2ec7a579f2823fbdc93036a65063f0dd3c3cfc9227dd8ff55161bf131
Main evidence archive index SHA-256: 7d28aee603b06896711cb83cbdb68041a05f44e9b50a1e9d28216f866a3d1b6c
Archive verification: 118/118 entries matched SHA-256 and size; exact inventory matched.
Candidate source verification: every source-manifest row for 156 parent files and 629 main-overlay files matched the frozen candidate bytes.
R3r3 original source and tests: all four preserved code/test files match the captured R3r3 snapshot manifest. R3r3 is provenance; the candidate uses the R4 authority source.

## Independent fake-only test replay

- Parent R4 issuer/store/control: 44 passed, 0 failed/error.
- Main bridge selected nodes: 3 passed, 0 failed/error.
- Main five-file bridge focus: 73 passed, 0 failed/error.
- Additional cancellation-control file: 20 passed, 0 failed/error.

Total: 140 passing executions across the four groups. The extra control file is a separate focus; do not interpret this sum as a count of unique test node IDs.

The independent copy needed test-only path changes because the frozen parent and extra control tests hard-code the original execution/risk/base/monitor source roots. Those constants were redirected to separately hash-verified package copies solely in this QA copy; the exact diff is in test-path-adaptations.diff. Production source bytes were not changed.

Initial harness failures are retained in the receipt: the first parent run preceded copying the guard module; the first guarded parent run rejected its hard-coded external roots; the first three-node main run had no copied guard directory; and the first supplementary control collection used external roots rejected by the guard. Final guarded runs passed after the QA-only setup/adaptations.

The successful guard logs recorded zero origin denials, native-import attempts, non-loopback network attempts, or protected private-config attempts. Guarded imports were limited to the explicitly mapped parent/base/execution/risk/monitor packages. Test fixtures remained under per-run temp roots.

## R4 stricter fake authority and R3r3 provenance

R4 retains a code-owned exact offline fake allowlist binding strategy, provider, account and policy, and requires a matching simulation/replay/offline/managed_execution capability contract plus offline fake risk scope for that account. The 44-test parent focus includes constructor negatives for CTP provider, wrong account, wrong strategy and the added wrong-policy case. Those cases require rejection before SQLite authority database creation.

R3r3 original fake authority SHA-256: d902a376cb28fd40bbab6a13542491d1080f2d8e477f695345e06bacd3349ba5. R4 effective fake authority SHA-256: ff31893935aed8ac7944c5f720eb46553298cf593553dbbe64ad74583b89dc06. The original R3r3 implementation is preserved but not reused in the composite. Candidate test diffs document contract/policy fixture adaptation and account-property adaptation for the stricter R4 authority. The additional wrong-policy test delta is preserved separately in the frozen candidate provenance.

## Version identity blocker

Candidate pyproject version: 0.15.5
Source-only metadata version: 0.15.5
Base parent pyproject version: 0.15.5
Candidate and base parent pyproject bytes match: True
The base parent authority SHA-256 is bf6b2db7a65463d8f3ddc3b55232961103df75edc2bdb8cc20080c6034ee0058, while R4 authority is ff31893935aed8ac7944c5f720eb46553298cf593553dbbe64ad74583b89dc06. Thus changed source bytes occupy the same existing 0.15.5 distribution identity. No wheel was built or installed; version/pin/release identity remains a blocker.

## Limits

This is fake/source-only contract evidence. It does not authenticate a real external provider cancellation or prove account authority or a live route. No SDK/native/provider/account/private config/non-loopback network was exercised. No default route, pin, release artifact or production source changed. G6-P, G6-S and G7-S are not accepted.

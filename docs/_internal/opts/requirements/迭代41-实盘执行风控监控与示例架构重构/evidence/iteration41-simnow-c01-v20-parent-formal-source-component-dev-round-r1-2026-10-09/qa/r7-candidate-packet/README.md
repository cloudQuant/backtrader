# SimNow C01 V20 parent formal composition R7 candidate

Status: `CANDIDATE_ONLY / PENDING_INDEPENDENT_STATIC_REVIEW_AND_ROOT_GUARDED_SOURCE_FAKE_QA`.

R7 carries the frozen 26-parent / 23-child source composition forward. All 26 production source rows are unchanged from R1. The only source/test byte change in this packet is the function-scoped fixture `tests/unit/runtime/test_certification_simnow_c01_rootseal_custody_v1_source_fake.py`, whose `env` fixture now snapshots seven `sys.modules` bindings before its first load and restores each old object (or removes a formerly absent name) in `finally`. This covers setup failures as well as normal teardown and preserves pre-existing canonical protocol and worker module identities.

R6 Root QA collected and passed all 118 calls with zero failures, skips, xfails, xpasses, warnings, or collection errors, but correctly returned `SOURCE_FAKE_FAILED`: two test-owned aliases for the loaded V17 root and custody modules remained after fixture teardown. R7 fixes the fixture lifetime at its owner. The strict parent postcondition still requires the same three persistent canonical module identities and requires all other declared ephemeral runtime aliases to be absent; no harness waiver or unconditional cleanup was added.

The suite remains eight focused files and 118 expected calls. The source-only selected-package namespace, production-loaded 26-module composition, guarded subprocess policy, root-only fixed suite, exact public source origins, pre/post source pins, minimal child environment, fresh external pytest configuration, separate standard-library temp directory, nested pytest basetemp, strict pass/skip/xfail/xpass/warning/collection gates, and forbidden-operation counter gates retain the R6 contract. Sourcefake tests do not establish native cleanup, provider/account behavior, or a formal C01 PASS.

The exact production-loaded V20 → V17 invocation receipt → formal adjudicator → completion composition check remains the unchanged R1 input and is recorded separately in `qa/composition-result.txt`. That evidence does not review or execute the changed R7 fixture.

`qa/command.txt` records the Root harness command. `qa/result.txt` is intentionally `NOT RUN` until the frozen R7 harness receives independent static review and Root performs its own guarded QA. No actual activation was run for this packet.

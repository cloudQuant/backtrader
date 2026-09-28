# 007 timeout-helper fail-close candidate

Status: isolated candidate only. The shared repository source was restored to its frozen preimage. Disposition remains NO_WRITE / LIVE_NO_GO.

## Frozen artifacts

- Source preimage: preimage/ctp_example_support.py
- Candidate source postimage: postimage/ctp_example_support.py
- New unit-test postimage: postimage/tests/unit/test_iteration41_007_live_timeout_failclose.py; the preimage path is absent.
- Exact unified patch: patch.diff at the candidate root.
- Fake pre/post probe: qa/fake_probe.py
- Hash manifest: SHA256SUMS.txt

The source postimage changes import threading to the explicit compatibility re-export import threading as threading, retaining the module attribute while satisfying Ruff after the old timer implementation is removed. The helper raises the standard legacy_direct_execution_not_supported error before inspecting the supplied Cerebro or timeout, creating a timer, or calling run(). The new unit test uses a Cerebro Bomb, a timer Bomb, SDK import guards, and socket-operation guards.

## Replay and checks

Exact patch replay was run with current directory D:\temp\ac41-63-007-run-timeout-failclose-candidate-2026-09-28\replay-v2 and core.autocrlf=true. From that directory, git apply --check followed by git apply succeeded. The replayed source SHA-256 equals the source postimage hash; the replayed unit-test SHA-256 equals the test postimage hash.

Ruff check with the repository pyproject.toml passed on the replayed source and unit test. The focused unit test passed: 1 passed, 1 existing pytest configuration warning. The fake-only pre/post probe passed: preimage reached only a fake Cerebro and fake Timer; candidate raised the standard legacy error with zero Cerebro accesses, zero timer calls, zero blocked socket calls, and no bt_api_py import. No provider, SDK, credential, account, native session, or real network operation was used.

## Static call-site and boundary review

The repository has five calls to this 007 helper, all in retired live-runner _legacy_main bodies that begin with an unconditional legacy_direct_execution_error. The runner main and CLI fences reject or dispatch to the fixed config-first runtime before the historical runner body can run. The candidate blocks only the retained 007 timeout helper.

Public BtApiStore, BtApiBroker, and BtApiFeed constructors remain available elsewhere, and a caller can still run a manually assembled live Cerebro through library APIs. Starting the current CTP Store can still reach its provider connection path. Current base Store CTP submit/cancel checks and low-level native-wrapper send checks are separate controls. This patch does not establish writer closure, account-wide isolation, or live acceptance; NO_WRITE / LIVE_NO_GO remains.
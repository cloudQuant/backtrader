# Binance TH01 account_full R2 source-component delivery — draft R1

**Evidence status:** SOURCE_FAKE_PRODUCER_COMPONENT_ONLY. Delivery is pending independent packet/helper review and Root partial-index staging. This record does not claim commit acceptance, provider/account acceptance, actual worker/Pipe behavior, or formal TH01 PASS.

## Repository and scope

Repository D:/source_code/backtrader, branch dev, current base HEAD 934e30b55c078a42517c1c758a45eacb09a2b740 (whose Git parent is dc8f97061245e5af7131e1ad8d9964d3462fc609). The proposed delivery commit's parent is the current base HEAD, 934e30b55c078a42517c1c758a45eacb09a2b740. Proposed code closure has exactly five paths: R1 shared-helper source, R2 source and focused test, plus models.py and runner.py selected from clean HEAD with only the exact reviewed hunks recorded in delivery-manifest.json. The current dirty models.py and runner.py checkouts remain byte-for-byte preserved. Inherited R9, the account-window wrapper, owner and package dependencies are excluded from restaging.

The proposed commit scope is 17 files: five code paths, two prior R2 review artifacts, one R17 static review, six exact Root R17 artifacts, this round record, the manifest, and .gitattributes. There are 16 exact -text payload rules: the 13 normal payload files, the two selected overlay paths, and the manifest. No unrelated dirty source/test files are included.

## R17 source-fake acceptance evidence

Root invoked the R17 frozen wrapper once at the pinned 934e30 HEAD using one isolated source-fake pytest child. Result .codex-tmp/binance_account_full_r2_root_source_qa_r17_20261009.json is archived as qa/r17-result.json and pinned by the manifest. Root status is SOURCE_FAKE_PRODUCER_COMPONENT_ONLY; child exit 0; nine collected and nine passed; zero failed, other, skipped/xfail, pytest warnings, Python warnings, or candidate denials. All 19 selected input pins, selected checkout-input status, and staging index pre/post checks matched.

The global worktree status changed during the child. The QA result records that fact; it does not claim global status unchanged. The candidate did not use an actual worker/Pipe, provider/account, network, native, private-input, or external opaque/software path; formal TH01 PASS is false. The isolated pytest child is source-fake QA only.

## Reviews and provenance

The existing R2 source review is GO_SOURCE_FAKE_COMPONENT_ONLY. The R17 pre-invocation static review is GO_ROOT_SOURCE_FAKE_QA_ONCE and pins the exact wrapper/generated source/inventory. Both review files and their exact pinned inputs are archived under qa/.

The models blob is reconstructed from parent HEAD models.py by adding default position_side, time_in_force, request_digest fields to PlannedOperation and default position_side/time_in_force fields to OrderState. The runner blob is reconstructed from parent HEAD runner.py by appending only venue: str | None = None to _plan. delivery-manifest.json pins each base and selected byte size, SHA-256, and Git blob OID. A read-only transform reproduced both selected blobs; no Git object was written during preparation.

## Root staging sequence

The additive helper .codex-tmp/binance_th01_account_full_r2_partial_index_delivery_r2_20261009.py has separate stage and postcommit modes and does not commit. Root must first receive independent GO on the exact manifest and helper. Then run its stage command with the manifest SHA printed in the delivery handoff, inspect the exact staged scope, and use the configured normal Git commit. After that commit, run its separate postcommit command with the same manifest path and SHA. Do not stage whole dirty models.py or runner.py, inherited R9, or unrelated worktree changes.

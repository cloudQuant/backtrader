# SimNow C01 V20 preparation source support — delivery proposal R1

Status: FROZEN_MINIMAL_SCOPE_PROPOSAL_FOR_ROOT_STAGE. This record is bound to the post-OKX dev parent 5b8f9f10f063ddb7b68b29e57b6f55fbd545aec2; no Git/index mutation or QA rerun was performed by this proposal author.

## Scope

The proposed scope is recorded with exact size/SHA-256 pins in manifest.json. It includes the R5 preparation source and its source-fake test, the exact R2 bounded-precheck and caller source dependencies, the two Root script source bindings, the R1/R5/R6 packets directly used by Root R6, the exact Root R6 result, and the R6 independent static review. The older R2 preparation helper and its failure history are excluded.

The 42 input rows that Root pinned before and after R6 classify as 16 R1/R5 packet artifact rows plus 26 public source rows. Of the public rows, 21 were byte-identical to HEAD, three were clean CRLF checkout forms whose LF-normalized bytes equal HEAD, and two were the Root scripts included as source-binding dependencies. The three CTP files remain untouched inherited files.

## Acceptance evidence

Root consumed R6 once (c4119c, run e670c46189d64a81a6be0bb86eed27a8) at 902d55daa397d601a947141b6a87eb1ca1df4d0a. The exact result is 20,242 bytes / 108a9e98eecf2038f289f4cef2f012bb75fc52a41c6ab371bc72595c3c329fd2: 12 collected and 12 passed, pytest exit 0, zero warnings, errors, skips, guard attempts, source pin changes, packet changes, or Root HEAD/index changes. Root readback reference: f9f415. The independent R6 review is 3,415 bytes / e7fb96fc1c33439b1e4dbc9dcbaeae8c5762dd87e8dfd12eaac6c52746e9fa59, static review only.

Evidence level is SOURCE_FAKE_PREPARATION_SUPPORT_ONLY. The R6 run did not invoke the credential-free Gate, create a candidate process, read software payloads, perform account/provider work, or produce a formal C01 PASS. The official C01 PASS count remains 0.

## Source closure and limits

The R5 test loads the exact R2 precheck/caller source pins and composes the exact lease-bound 26 public source bytes. The two Root scripts are preserved solely because they are exact source bindings in that map. Their inclusion does not accept the script's operational entrypoints or authorize invocation. Twenty-four public source inputs are inherited from dev; the three clean CRLF forms normalize to their committed HEAD blobs.

The R6 runner and result remain bound to the original 902d55 source checkpoint and its 2,863,553-byte raw index proof. Delivery on 5b8f9f records the historical successful run; it does not claim that the same HEAD-bound harness was rerun after the parent advanced. No private or software payload was read for this proposal.
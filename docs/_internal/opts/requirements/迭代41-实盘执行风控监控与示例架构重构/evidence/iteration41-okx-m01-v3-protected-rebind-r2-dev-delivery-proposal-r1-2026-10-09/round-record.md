# OKX M01 V3 protected metadata rebind R2 delivery proposal

Status: proposed coherent source delivery for the existing Backtrader `dev` checkout. This packet is not staged or committed. Root reported the current HEAD prefix as `dc8f`; Root should refresh the full base commit before staging. No Git command was run while preparing this proposal.

## Scope

The proposed delivery contains exactly ten files: the unregistered fixed-path helper and its focused fake-OS tests; the frozen source-candidate README and pins; the narrow independent `_require` binding review; exact copies of Root's focused QA script and result; this round record; a delivery manifest; and a byte-preservation rules proposal. It does not copy or restage the accepted 19-row source map, the source integration packet, the canonical reader/entry/runner, or the shared private helper.

## Verification

Root's R2 focused QA ran once (tool `cddd14`): exit 0, 11/11 tests passed, four guard self-checks passed, no candidate-blocked categories, input pins unchanged, and live helper/reader function identity, code, and globals preserved. Evidence level is `SOURCE_FAKE_COMPONENT_ONLY`. The prior R1 harness (`be58b7bd…` / 7,933 B) was rejected at a cold `colorama` `WinDLL` audit before reaching the candidate or tests; Root retained it and corrected only the harness preload/result-path handling in R2. The R1 attempt produced no candidate result.

The static review of the `_require` binding fix is `GO_REQUIRE_BINDING_FIX_STATIC_ONLY`, 1,834 B / SHA-256 `fe530a9e8323a5ee492c1d7b1fc80028423df70ad5fd032143ce1790c965f2d4`. It closes the reviewed reader-global binding defect. Root's caller must still bind the exact CUv2 private-helper source, code, and globals throughout the call.

## Metadata generation and evidence level

The accepted prior protected metadata state was rebound to the R2 map digest `db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3`; backup generation `r2-20261009-preservation` is consumed. The candidate validates that old R2 state and targets current map digest `07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3`, using only the fixed new backup child `r3-20261009-preservation`. The helper preserves old bytes in exclusive owner-only backup files, updates map before deployment, verifies same-handle readback and held identities/ACLs, and retains uncertain contexts on write or close uncertainty.

The Root QA used fake protected-OS leaves. It did not read or update protected deployment metadata, call WinAPI, access credentials/provider/account data, or establish a formal M01 result. Formal M01 remains 0. This round is source/fake-only and does not authorize a protected metadata invocation.

## Inherited dependencies and delivery boundary

The exact 19-row source map (`07f0…` / 2,877 B), current integration review note (`c09…` / 3,820 B), and reviewed integration test (`21d4…` / 9,809 B) remain inherited from the accepted source integration round. The map binds the current reader (`5a8f…` / 68,215 B), entry (`e061…` / 5,952 B), runner (`d498…` / 1,992 B), private helper (`b866…` / 17,537 B), and the other 15 accepted public source rows. These dependencies are referenced by hash and are not repeated in this delivery.

The staging proposal is the ten paths in `delivery-manifest.json`, plus the exact `-text` rules listed in `byte-preservation-rules-proposal.txt`. The shared `.gitattributes` file is not modified in this preparation. Root may stage only the reviewed ten files and corresponding rules after confirming the current full HEAD; preserve unrelated working-tree state and leave the index empty until that scoped acceptance step.

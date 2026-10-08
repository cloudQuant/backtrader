# C01 V18 cleanup capsule R3 independent review

**Verdict: GO_SOURCE_FAKE_ONLY.** R3 pins and copied public references match. The isolated focused source/fake suite passed 23 tests with one existing pytest configuration warning.

R3 repairs the R2 control-flow defect. The final pre-close checks now execute before the captured close function is returned: they bind the same KEEPALIVE list and holder, re-find the same lease and unresolved-list object, validate the open lease state and independent expected-map snapshot, recheck the held CUv2 bytes and source map, and validate the wrapper module and exact empty unresolved-job list. Only then does it rebind the frozen driver and method identities and directly call the captured class function.

Focused fake cases verify that post-admission changes to the KEEPALIVE list, holder membership, expected map, or lease lifecycle state block before close. The previous R1 and R2 HOLD packets remain frozen. This review authorizes only the source/fake contract; Root must separately verify and authorize a one-use cleanup on the original owner state. No actual cleanup or activation was performed, and official C01 PASS remains zero.
